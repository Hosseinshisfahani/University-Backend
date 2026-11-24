"""Appointment booking, confirmation, cancellation, and admin move."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.kernel.finance import services as finance_services
from apps.kernel.finance.models import LedgerEntry

from ..models import Appointment, ProviderServiceOffer, ServiceType, Slot
from ..policy import cancel_window_hours, refund_on_late_cancel
from ..signals import (
    appointment_booked,
    appointment_cancelled,
    appointment_completed,
    appointment_confirmed,
    appointment_moved,
)

OFFLINE_PAYMENT_REF = "offline"
HOLD_MINUTES = 15


class BookingError(Exception):
    pass


def _release_expired_hold(slot: Slot, now) -> Slot:
    if slot.status == Slot.Status.HELD and slot.hold_expires_at and slot.hold_expires_at < now:
        slot.status = Slot.Status.OPEN
        slot.service_type = None
        slot.hold_expires_at = None
        slot.save(update_fields=["status", "service_type", "hold_expires_at", "updated_at"])
    return slot


@transaction.atomic
def book_slot(*, customer, slot_id: int, service_type_id: int) -> Appointment:
    slot = Slot.objects.select_for_update().select_related("provider").get(pk=slot_id)
    now = timezone.now()
    slot = _release_expired_hold(slot, now)
    if slot.status != Slot.Status.OPEN or Appointment.objects.filter(slot=slot).exists():
        raise BookingError("Slot is not available.")

    service_type = ServiceType.objects.filter(pk=service_type_id, is_active=True).first()
    if service_type is None:
        raise BookingError("Session type not found.")
    if service_type.institute_id != slot.institute_id:
        raise BookingError("Session type not found.")
    if not ProviderServiceOffer.objects.filter(
        provider=slot.provider,
        service_type=service_type,
        is_active=True,
    ).exists():
        raise BookingError("This provider does not offer that service.")
    if timedelta(minutes=service_type.duration_minutes) > (slot.ends_at - slot.starts_at):
        raise BookingError("This session type does not fit in the selected time.")

    slot.status = Slot.Status.HELD
    slot.service_type = service_type
    slot.hold_expires_at = now + timedelta(minutes=HOLD_MINUTES)
    slot.save(update_fields=["status", "service_type", "hold_expires_at", "updated_at"])

    appointment = Appointment.objects.create(
        slot=slot,
        customer=customer,
        provider=slot.provider,
        service_type=service_type,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
        status=Appointment.Status.PENDING_PAYMENT,
        price_snapshot=service_type.price,
        institute_id=slot.institute_id,
    )
    appointment_booked.send(sender=Appointment, appointment=appointment)
    return appointment


@transaction.atomic
def confirm_appointment_payment(
    *,
    appointment: Appointment,
    payment_ref: str,
    idempotency_key: str,
    allow_offline: bool = False,
) -> Appointment:
    appointment = Appointment.objects.select_for_update().select_related(
        "customer", "provider", "slot"
    ).get(pk=appointment.pk)
    if appointment.status != Appointment.Status.PENDING_PAYMENT:
        raise BookingError("Appointment is not awaiting payment.")
    if payment_ref == OFFLINE_PAYMENT_REF and not allow_offline:
        raise BookingError("Offline payment is admin-only.")

    ledger_ref = ""
    if payment_ref != OFFLINE_PAYMENT_REF:
        entry = finance_services.debit_wallet(
            user=appointment.customer,
            amount=Decimal(appointment.price_snapshot),
            entry_type=LedgerEntry.EntryType.APPOINTMENT_CAPTURE,
            idempotency_key=idempotency_key,
            reference=f"booking.appointment:{appointment.pk}",
            description=f"Appointment {appointment.pk}",
            institute=appointment.institute,
        )
        ledger_ref = f"finance.ledger:{entry.pk}"
    appointment.status = Appointment.Status.CONFIRMED
    appointment.payment_ref = payment_ref
    appointment.deposit_ledger_ref = ledger_ref
    appointment.save(update_fields=["status", "payment_ref", "deposit_ledger_ref", "updated_at"])
    slot = appointment.slot
    slot.status = Slot.Status.BOOKED
    slot.hold_expires_at = None
    slot.save(update_fields=["status", "hold_expires_at", "updated_at"])
    appointment = Appointment.objects.select_related("customer", "provider").get(pk=appointment.pk)
    appointment_confirmed.send(sender=Appointment, appointment=appointment)
    return appointment


def _patient_cancel_policy(appointment: Appointment) -> str:
    window = timedelta(hours=cancel_window_hours(appointment.institute))
    if appointment.starts_at - timezone.now() > window or refund_on_late_cancel(appointment.institute):
        return Appointment.RefundPolicy.FULL_REFUND
    return Appointment.RefundPolicy.FORFEIT


@transaction.atomic
def cancel_appointment(*, appointment: Appointment, canceled_by: str, reason: str = "") -> Appointment:
    """canceled_by: 'patient' | 'therapist' | 'admin' (kept for the existing status names)."""
    appointment = Appointment.objects.select_for_update().select_related(
        "customer", "provider", "slot", "institute"
    ).get(pk=appointment.pk)
    if appointment.status not in (Appointment.Status.PENDING_PAYMENT, Appointment.Status.CONFIRMED):
        raise BookingError("Appointment cannot be canceled.")

    was_confirmed = appointment.status == Appointment.Status.CONFIRMED
    wallet_captured = bool(appointment.deposit_ledger_ref)
    captured = appointment.status == Appointment.Status.CONFIRMED and wallet_captured
    if canceled_by == "patient":
        new_status = Appointment.Status.CANCELED_BY_PATIENT
        policy = _patient_cancel_policy(appointment) if captured else Appointment.RefundPolicy.NONE
    elif canceled_by in {"therapist", "admin"}:
        new_status = (
            Appointment.Status.CANCELED_BY_THERAPIST
            if canceled_by == "therapist"
            else Appointment.Status.CANCELED_BY_ADMIN
        )
        policy = Appointment.RefundPolicy.FULL_REFUND if captured else Appointment.RefundPolicy.NONE
    else:
        raise BookingError("Invalid canceled_by.")

    refund_ref = ""
    if policy == Appointment.RefundPolicy.FULL_REFUND:
        entry = finance_services.credit_wallet(
            user=appointment.customer,
            amount=Decimal(appointment.price_snapshot),
            entry_type=LedgerEntry.EntryType.REFUND,
            idempotency_key=f"appt-refund:{appointment.pk}",
            reference=f"booking.appointment:{appointment.pk}",
            description="Appointment cancellation refund",
            institute=appointment.institute,
        )
        refund_ref = f"finance.ledger:{entry.pk}"

    appointment.status = new_status
    appointment.canceled_at = timezone.now()
    appointment.cancellation_reason = reason
    appointment.refund_policy_applied = policy
    appointment.refund_ledger_ref = refund_ref
    appointment.save()

    slot = appointment.slot
    slot.status = Slot.Status.BLOCKED
    slot.hold_expires_at = None
    slot.save(update_fields=["status", "hold_expires_at", "updated_at"])
    if was_confirmed:
        appointment = Appointment.objects.select_related("customer", "provider").get(pk=appointment.pk)
        appointment_cancelled.send(sender=Appointment, appointment=appointment)
    return appointment


@transaction.atomic
def move_appointment(*, appointment: Appointment, new_slot_id: int) -> Appointment:
    appointment = Appointment.objects.select_for_update().select_related(
        "customer", "provider", "slot", "service_type"
    ).get(pk=appointment.pk)
    if appointment.status not in (Appointment.Status.PENDING_PAYMENT, Appointment.Status.CONFIRMED):
        raise BookingError("Only active appointments can be moved.")

    new_slot = Slot.objects.select_for_update().select_related("provider").get(pk=new_slot_id)
    if new_slot.institute_id != appointment.institute_id:
        raise BookingError("Target slot is not open.")
    if new_slot.status != Slot.Status.OPEN or Appointment.objects.filter(slot=new_slot).exists():
        raise BookingError("Target slot is not open.")
    if timedelta(minutes=appointment.service_type.duration_minutes) > (new_slot.ends_at - new_slot.starts_at):
        raise BookingError("This session type does not fit in the selected time.")

    old_slot = appointment.slot
    old_slot.status = Slot.Status.OPEN
    old_slot.service_type = None
    old_slot.hold_expires_at = None
    old_slot.save(update_fields=["status", "service_type", "hold_expires_at", "updated_at"])

    new_slot.status = (
        Slot.Status.BOOKED if appointment.status == Appointment.Status.CONFIRMED else Slot.Status.HELD
    )
    new_slot.service_type = appointment.service_type
    new_slot.save(update_fields=["status", "service_type", "updated_at"])

    appointment.slot = new_slot
    appointment.provider = new_slot.provider
    appointment.starts_at = new_slot.starts_at
    appointment.ends_at = new_slot.ends_at
    appointment.save(update_fields=["slot", "provider", "starts_at", "ends_at", "updated_at"])
    if appointment.status == Appointment.Status.CONFIRMED:
        appointment = Appointment.objects.select_related("customer", "provider").get(pk=appointment.pk)
        appointment_moved.send(sender=Appointment, appointment=appointment)
    return appointment


@transaction.atomic
def admin_book_appointment(*, customer, slot_id: int, service_type_id: int, payment: str) -> Appointment:
    """payment: 'pending' | 'wallet' | 'offline'."""
    appointment = book_slot(customer=customer, slot_id=slot_id, service_type_id=service_type_id)
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


@transaction.atomic
def complete_appointment(*, appointment: Appointment) -> Appointment:
    appointment = Appointment.objects.select_for_update().get(pk=appointment.pk)
    if appointment.status != Appointment.Status.CONFIRMED:
        raise BookingError("Only confirmed appointments can be completed.")
    if appointment.ends_at > timezone.now():
        raise BookingError("Appointment has not ended yet.")
    appointment.status = Appointment.Status.COMPLETED
    appointment.save(update_fields=["status", "updated_at"])
    appointment_completed.send(sender=Appointment, appointment=appointment)
    return appointment
