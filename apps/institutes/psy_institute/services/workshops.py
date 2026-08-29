"""Workshop enrollment: hold seat, confirm payment, cancel/refund."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.finance import services as finance_services
from apps.finance.models import LedgerEntry

from ..models import (
    PatientProfile,
    Workshop,
    WorkshopCertificate,
    WorkshopEnrollment,
    WorkshopSession,
    WorkshopSessionProgress,
)

HOLD_MINUTES = 15
CANCEL_FULL_REFUND_HOURS = 24


class WorkshopError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "workshop_error",
        extra: dict | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.extra = extra or {}


def _occupying_q(*, now=None):
    now = now or timezone.now()
    return Q(status=WorkshopEnrollment.Status.ACTIVE) | Q(
        status=WorkshopEnrollment.Status.PENDING_PAYMENT,
        hold_expires_at__gt=now,
    )


def occupied_seats(workshop: Workshop, *, now=None) -> int:
    return (
        WorkshopEnrollment.objects.filter(workshop=workshop)
        .filter(_occupying_q(now=now))
        .count()
    )


def seats_remaining(workshop: Workshop, *, now=None) -> int:
    return max(0, workshop.capacity - occupied_seats(workshop, now=now))


def _hold_still_valid(enrollment: WorkshopEnrollment, now) -> bool:
    return (
        enrollment.status == WorkshopEnrollment.Status.PENDING_PAYMENT
        and enrollment.hold_expires_at is not None
        and enrollment.hold_expires_at > now
    )


@transaction.atomic
def enroll_in_workshop(
    *,
    workshop: Workshop,
    patient: PatientProfile,
) -> WorkshopEnrollment:
    """
    Hold a seat for HOLD_MINUTES (pending_payment) with price_snapshot.
    Free workshops (price == 0) activate immediately.
    """
    workshop = Workshop.objects.select_for_update().get(pk=workshop.pk)
    now = timezone.now()

    enrollment = (
        WorkshopEnrollment.objects.select_for_update()
        .filter(workshop=workshop, patient=patient)
        .first()
    )

    if enrollment and enrollment.status == WorkshopEnrollment.Status.ACTIVE:
        raise WorkshopError("Already enrolled.", code="already_enrolled")

    if enrollment and _hold_still_valid(enrollment, now):
        return enrollment

    # Seat already held by this patient (expired) does not count in occupied
    occupied = occupied_seats(workshop, now=now)
    if occupied >= workshop.capacity:
        raise WorkshopError("Workshop is full.", code="workshop_full")

    price = Decimal(workshop.price)
    hold_until = now + timedelta(minutes=HOLD_MINUTES)

    if enrollment:
        enrollment.status = WorkshopEnrollment.Status.PENDING_PAYMENT
        enrollment.price_snapshot = price
        enrollment.hold_expires_at = hold_until
        enrollment.payment_ref = ""
        enrollment.deposit_ledger_ref = ""
        enrollment.refund_ledger_ref = ""
        enrollment.canceled_at = None
        enrollment.cancellation_reason = ""
        enrollment.save()
    else:
        enrollment = WorkshopEnrollment.objects.create(
            workshop=workshop,
            patient=patient,
            status=WorkshopEnrollment.Status.PENDING_PAYMENT,
            price_snapshot=price,
            hold_expires_at=hold_until,
        )

    if price == 0:
        enrollment.status = WorkshopEnrollment.Status.ACTIVE
        enrollment.hold_expires_at = None
        enrollment.payment_ref = "free"
        enrollment.save(
            update_fields=[
                "status",
                "hold_expires_at",
                "payment_ref",
                "updated_at",
            ]
        )

    return enrollment


@transaction.atomic
def confirm_workshop_enrollment(
    *,
    enrollment: WorkshopEnrollment,
    payment_ref: str,
    idempotency_key: str,
) -> WorkshopEnrollment:
    enrollment = (
        WorkshopEnrollment.objects.select_for_update()
        .select_related("patient__user", "workshop")
        .get(pk=enrollment.pk)
    )
    now = timezone.now()

    if enrollment.status == WorkshopEnrollment.Status.ACTIVE:
        return enrollment

    if enrollment.status != WorkshopEnrollment.Status.PENDING_PAYMENT:
        raise WorkshopError(
            "Enrollment is not awaiting payment.", code="invalid_status"
        )

    if enrollment.hold_expires_at and enrollment.hold_expires_at < now:
        raise WorkshopError(
            "Hold expired. Please register again.",
            code="hold_expired",
        )

    amount = Decimal(enrollment.price_snapshot)
    if amount == 0:
        enrollment.status = WorkshopEnrollment.Status.ACTIVE
        enrollment.hold_expires_at = None
        enrollment.payment_ref = payment_ref or "free"
        enrollment.save(
            update_fields=["status", "hold_expires_at", "payment_ref", "updated_at"]
        )
        return enrollment

    try:
        entry = finance_services.debit_wallet(
            user=enrollment.patient.user,
            amount=amount,
            entry_type=LedgerEntry.EntryType.WORKSHOP_PURCHASE,
            idempotency_key=idempotency_key,
            reference=f"psy.workshop:{enrollment.workshop_id}",
            description=enrollment.workshop.title,
        )
    except finance_services.InsufficientFunds as exc:
        wallet = finance_services.get_or_create_wallet(enrollment.patient.user)
        raise WorkshopError(
            str(exc),
            code="insufficient_funds",
            extra={
                "required": str(amount),
                "balance": str(wallet.balance),
                "shortfall": str(max(Decimal("0"), amount - wallet.balance)),
            },
        ) from exc

    enrollment.status = WorkshopEnrollment.Status.ACTIVE
    enrollment.hold_expires_at = None
    enrollment.payment_ref = payment_ref
    enrollment.deposit_ledger_ref = f"finance.ledger:{entry.pk}"
    enrollment.save(
        update_fields=[
            "status",
            "hold_expires_at",
            "payment_ref",
            "deposit_ledger_ref",
            "updated_at",
        ]
    )
    return enrollment


@transaction.atomic
def cancel_workshop_enrollment(
    *,
    enrollment: WorkshopEnrollment,
    canceled_by: str,
    reason: str = "",
) -> WorkshopEnrollment:
    """
    canceled_by: 'patient' | 'admin'
    - pending_payment: release hold, no refund
    - active + patient: full refund if >24h before starts_at else forfeit
    - active + admin: always full refund → status refunded
    """
    enrollment = (
        WorkshopEnrollment.objects.select_for_update()
        .select_related("patient__user", "workshop")
        .get(pk=enrollment.pk)
    )

    if enrollment.status not in (
        WorkshopEnrollment.Status.PENDING_PAYMENT,
        WorkshopEnrollment.Status.ACTIVE,
    ):
        raise WorkshopError("Enrollment cannot be canceled.", code="invalid_status")

    now = timezone.now()
    refund = False

    if enrollment.status == WorkshopEnrollment.Status.PENDING_PAYMENT:
        new_status = WorkshopEnrollment.Status.CANCELED
    elif canceled_by == "admin":
        new_status = WorkshopEnrollment.Status.REFUNDED
        refund = Decimal(enrollment.price_snapshot) > 0
    elif canceled_by == "patient":
        starts = enrollment.workshop.starts_at
        if (
            Decimal(enrollment.price_snapshot) > 0
            and starts
            and starts - now > timedelta(hours=CANCEL_FULL_REFUND_HOURS)
        ):
            new_status = WorkshopEnrollment.Status.REFUNDED
            refund = True
        else:
            new_status = WorkshopEnrollment.Status.CANCELED
            refund = False
    else:
        raise WorkshopError("Invalid canceled_by.", code="invalid_actor")

    refund_ref = ""
    if refund:
        entry = finance_services.credit_wallet(
            user=enrollment.patient.user,
            amount=Decimal(enrollment.price_snapshot),
            entry_type=LedgerEntry.EntryType.REFUND,
            idempotency_key=f"workshop-refund:{enrollment.pk}",
            reference=f"psy.workshop:{enrollment.workshop_id}",
            description="Workshop enrollment refund",
        )
        refund_ref = f"finance.ledger:{entry.pk}"

    enrollment.status = new_status
    enrollment.hold_expires_at = None
    enrollment.canceled_at = now
    enrollment.cancellation_reason = reason
    enrollment.refund_ledger_ref = refund_ref
    enrollment.save(
        update_fields=[
            "status",
            "hold_expires_at",
            "canceled_at",
            "cancellation_reason",
            "refund_ledger_ref",
            "updated_at",
        ]
    )
    return enrollment


def viewer_has_content_access(*, user, workshop: Workshop) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_staff or user.groups.filter(name="psy_admin").exists():
        return True
    if (
        hasattr(user, "therapist_profile")
        and workshop.instructor_id == user.therapist_profile.id
    ):
        return True
    if hasattr(user, "patient_profile"):
        return WorkshopEnrollment.objects.filter(
            workshop=workshop,
            patient=user.patient_profile,
            status=WorkshopEnrollment.Status.ACTIVE,
        ).exists()
    return False


def get_active_enrollment(*, user, workshop: Workshop) -> WorkshopEnrollment | None:
    if not user or not user.is_authenticated or not hasattr(user, "patient_profile"):
        return None
    return WorkshopEnrollment.objects.filter(
        workshop=workshop,
        patient=user.patient_profile,
        status=WorkshopEnrollment.Status.ACTIVE,
    ).first()


def progress_percent(*, enrollment: WorkshopEnrollment | None, workshop: Workshop) -> int | None:
    total = workshop.sessions.count()
    if enrollment is None:
        return None
    if total == 0:
        return 0
    done = WorkshopSessionProgress.objects.filter(
        enrollment=enrollment, session__workshop=workshop
    ).count()
    return round(100 * done / total)


def mark_session_complete(
    *,
    enrollment: WorkshopEnrollment,
    session: WorkshopSession,
) -> WorkshopSessionProgress:
    if enrollment.status != WorkshopEnrollment.Status.ACTIVE:
        raise WorkshopError("Active enrollment required.", code="forbidden")
    if session.workshop_id != enrollment.workshop_id:
        raise WorkshopError("Session does not belong to this workshop.", code="invalid_session")
    progress, _ = WorkshopSessionProgress.objects.get_or_create(
        enrollment=enrollment,
        session=session,
    )
    return progress


def issue_certificate(*, enrollment: WorkshopEnrollment) -> WorkshopCertificate:
    if enrollment.status != WorkshopEnrollment.Status.ACTIVE:
        raise WorkshopError("Active enrollment required.", code="forbidden")
    workshop = enrollment.workshop
    if not workshop.certificate_enabled:
        raise WorkshopError("Certificates are not enabled.", code="cert_disabled")
    total = workshop.sessions.count()
    if total < 1:
        raise WorkshopError(
            "Workshop has no sessions to complete.", code="no_sessions"
        )
    done = WorkshopSessionProgress.objects.filter(
        enrollment=enrollment, session__workshop=workshop
    ).count()
    if done < total:
        raise WorkshopError(
            "Complete all sessions before issuing a certificate.",
            code="incomplete",
            extra={"progress_percent": round(100 * done / total)},
        )
    existing = WorkshopCertificate.objects.filter(enrollment=enrollment).first()
    if existing:
        return existing
    import secrets

    code = f"PSY-WS-{enrollment.pk}-{secrets.token_hex(4).upper()}"
    return WorkshopCertificate.objects.create(
        enrollment=enrollment,
        certificate_code=code,
    )
