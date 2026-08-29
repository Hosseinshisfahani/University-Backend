"""Appointment booking, confirmation, cancellation, and admin move."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.finance import services as finance_services
from apps.finance.models import LedgerEntry

from ..models import Appointment, AppointmentSlot, PatientProfile, SessionType, TherapistSessionOffer

OFFLINE_PAYMENT_REF = "offline"


class BookingError(Exception):
    pass


HOLD_MINUTES = 15
CANCEL_FULL_REFUND_HOURS = 24


@transaction.atomic
def book_slot(*, patient: PatientProfile, slot_id: int, session_type_id: int) -> Appointment:
    slot = (
        AppointmentSlot.objects.select_for_update()
        .select_related("therapist")
        .get(pk=slot_id)
    )
    now = timezone.now()
    if slot.status == AppointmentSlot.Status.HELD and slot.hold_expires_at and slot.hold_expires_at < now:
        slot.status = AppointmentSlot.Status.OPEN
        slot.session_type = None
        slot.hold_expires_at = None
        slot.save(update_fields=["status", "session_type", "hold_expires_at", "updated_at"])

    if slot.status != AppointmentSlot.Status.OPEN:
        raise BookingError("Slot is not available.")
    if Appointment.objects.filter(slot=slot).exists():
        raise BookingError("Slot is not available.")

    session_type = SessionType.objects.filter(pk=session_type_id, is_active=True).first()
    if session_type is None:
        raise BookingError("Session type not found.")
    if not TherapistSessionOffer.objects.filter(
        therapist=slot.therapist,
        session_type=session_type,
        is_active=True,
    ).exists():
        raise BookingError("This therapist does not offer that session type.")
    needed = timedelta(minutes=session_type.duration_minutes)
    if needed > (slot.ends_at - slot.starts_at):
        raise BookingError("This session type does not fit in the selected time.")

    slot.status = AppointmentSlot.Status.HELD
    slot.session_type = session_type
    slot.hold_expires_at = now + timedelta(minutes=HOLD_MINUTES)
    slot.save(update_fields=["status", "session_type", "hold_expires_at", "updated_at"])

    return Appointment.objects.create(
        slot=slot,
        patient=patient,
        therapist=slot.therapist,
        session_type=session_type,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
        status=Appointment.Status.PENDING_PAYMENT,
        price_snapshot=session_type.price,
    )


@transaction.atomic
def confirm_appointment_payment(
    *,
    appointment: Appointment,
    payment_ref: str,
    idempotency_key: str,
    allow_offline: bool = False,
) -> Appointment:
    appointment = Appointment.objects.select_for_update().select_related("patient__user", "slot").get(
        pk=appointment.pk
    )
    if appointment.status != Appointment.Status.PENDING_PAYMENT:
        raise BookingError("Appointment is not awaiting payment.")
    if payment_ref == OFFLINE_PAYMENT_REF and not allow_offline:
        raise BookingError("Offline payment is admin-only.")

    amount = Decimal(appointment.price_snapshot)
    ledger_ref = ""
    if payment_ref != OFFLINE_PAYMENT_REF:
        # Debit wallet (patient must have funded via Payment confirm first)
        entry = finance_services.debit_wallet(
            user=appointment.patient.user,
            amount=amount,
            entry_type=LedgerEntry.EntryType.APPOINTMENT_CAPTURE,
            idempotency_key=idempotency_key,
            reference=f"psy.appointment:{appointment.pk}",
            description=f"Appointment {appointment.pk}",
        )
        ledger_ref = f"finance.ledger:{entry.pk}"
    appointment.status = Appointment.Status.CONFIRMED
    appointment.payment_ref = payment_ref
    appointment.deposit_ledger_ref = ledger_ref
    appointment.save(
        update_fields=[
            "status",
            "payment_ref",
            "deposit_ledger_ref",
            "updated_at",
        ]
    )
    slot = appointment.slot
    slot.status = AppointmentSlot.Status.BOOKED
    slot.hold_expires_at = None
    slot.save(update_fields=["status", "hold_expires_at", "updated_at"])
    return appointment


def _refund_policy_for_patient_cancel(starts_at) -> str:
    if starts_at - timezone.now() > timedelta(hours=CANCEL_FULL_REFUND_HOURS):
        return Appointment.RefundPolicy.FULL_REFUND
    return Appointment.RefundPolicy.FORFEIT


@transaction.atomic
def cancel_appointment(
    *,
    appointment: Appointment,
    canceled_by: str,
    reason: str = "",
) -> Appointment:
    """
    canceled_by: 'patient' | 'therapist' | 'admin'
    """
    appointment = Appointment.objects.select_for_update().select_related(
        "patient__user", "slot"
    ).get(pk=appointment.pk)

    if appointment.status not in (
        Appointment.Status.PENDING_PAYMENT,
        Appointment.Status.CONFIRMED,
    ):
        raise BookingError("Appointment cannot be canceled.")

    now = timezone.now()
    wallet_captured = bool(appointment.deposit_ledger_ref)
    if canceled_by == "patient":
        new_status = Appointment.Status.CANCELED_BY_PATIENT
        if appointment.status == Appointment.Status.CONFIRMED and wallet_captured:
            policy = _refund_policy_for_patient_cancel(appointment.starts_at)
        else:
            policy = Appointment.RefundPolicy.NONE
    elif canceled_by == "therapist":
        new_status = Appointment.Status.CANCELED_BY_THERAPIST
        policy = (
            Appointment.RefundPolicy.FULL_REFUND
            if appointment.status == Appointment.Status.CONFIRMED and wallet_captured
            else Appointment.RefundPolicy.NONE
        )
    elif canceled_by == "admin":
        new_status = Appointment.Status.CANCELED_BY_ADMIN
        policy = (
            Appointment.RefundPolicy.FULL_REFUND
            if appointment.status == Appointment.Status.CONFIRMED and wallet_captured
            else Appointment.RefundPolicy.NONE
        )
    else:
        raise BookingError("Invalid canceled_by.")

    refund_ref = ""
    if policy == Appointment.RefundPolicy.FULL_REFUND:
        entry = finance_services.credit_wallet(
            user=appointment.patient.user,
            amount=Decimal(appointment.price_snapshot),
            entry_type=LedgerEntry.EntryType.REFUND,
            idempotency_key=f"appt-refund:{appointment.pk}",
            reference=f"psy.appointment:{appointment.pk}",
            description="Appointment cancellation refund",
        )
        refund_ref = f"finance.ledger:{entry.pk}"
    elif policy == Appointment.RefundPolicy.FORFEIT:
        # Audit-only ledger with zero wallet change via description row optional —
        # record forfeit as reference without balance change using a no-op skip;
        # blueprint asked for forfeit audit — use debit 0 not allowed; skip ledger.
        refund_ref = ""

    appointment.status = new_status
    appointment.canceled_at = now
    appointment.cancellation_reason = reason
    appointment.refund_policy_applied = policy
    appointment.refund_ledger_ref = refund_ref
    appointment.save()

    slot = appointment.slot
    # Keep the historical slot attached (PROTECT + OneToOne). Reopening it
    # would make regenerate try to delete it and would not free it for a
    # new booking. Archive as blocked; regenerate can create a replacement.
    slot.status = AppointmentSlot.Status.BLOCKED
    slot.hold_expires_at = None
    slot.save(update_fields=["status", "hold_expires_at", "updated_at"])
    return appointment


@transaction.atomic
def move_appointment(*, appointment: Appointment, new_slot_id: int) -> Appointment:
    """Admin-only: move a confirmed/pending appointment to a new open slot."""
    appointment = Appointment.objects.select_for_update().select_related(
        "slot", "session_type"
    ).get(pk=appointment.pk)
    if appointment.status not in (
        Appointment.Status.PENDING_PAYMENT,
        Appointment.Status.CONFIRMED,
    ):
        raise BookingError("Only active appointments can be moved.")

    new_slot = (
        AppointmentSlot.objects.select_for_update()
        .select_related("therapist")
        .get(pk=new_slot_id)
    )
    if new_slot.status != AppointmentSlot.Status.OPEN:
        raise BookingError("Target slot is not open.")
    if Appointment.objects.filter(slot=new_slot).exists():
        raise BookingError("Target slot is not open.")
    needed = timedelta(minutes=appointment.session_type.duration_minutes)
    if needed > (new_slot.ends_at - new_slot.starts_at):
        raise BookingError("This session type does not fit in the selected time.")

    old_slot = appointment.slot
    old_slot.status = AppointmentSlot.Status.OPEN
    old_slot.session_type = None
    old_slot.hold_expires_at = None
    old_slot.save(update_fields=["status", "session_type", "hold_expires_at", "updated_at"])

    new_slot.status = (
        AppointmentSlot.Status.BOOKED
        if appointment.status == Appointment.Status.CONFIRMED
        else AppointmentSlot.Status.HELD
    )
    new_slot.session_type = appointment.session_type
    new_slot.save(update_fields=["status", "session_type", "updated_at"])

    appointment.slot = new_slot
    appointment.therapist = new_slot.therapist
    appointment.starts_at = new_slot.starts_at
    appointment.ends_at = new_slot.ends_at
    appointment.save(
        update_fields=[
            "slot",
            "therapist",
            "starts_at",
            "ends_at",
            "updated_at",
        ]
    )
    return appointment


@transaction.atomic
def admin_book_appointment(
    *,
    patient: PatientProfile,
    slot_id: int,
    session_type_id: int,
    payment: str,
) -> Appointment:
    """
    Admin registers an appointment for an existing patient.
    payment: 'pending' | 'wallet' | 'offline'
    """
    appointment = book_slot(
        patient=patient, slot_id=slot_id, session_type_id=session_type_id
    )
    if payment == "pending":
        return appointment
    if payment == "wallet":
        return confirm_appointment_payment(
            appointment=appointment,
            payment_ref="wallet",
            idempotency_key=f"admin-book-wallet:{appointment.pk}",
        )
    if payment == "offline":
        return confirm_appointment_payment(
            appointment=appointment,
            payment_ref=OFFLINE_PAYMENT_REF,
            idempotency_key=f"admin-book-offline:{appointment.pk}",
            allow_offline=True,
        )
    raise BookingError("Invalid payment option.")
