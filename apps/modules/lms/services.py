"""Course enrollment: hold a seat, confirm payment, cancel or refund.

Column names still say workshop. The service speaks in courses and users.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.kernel.finance import services as finance_services
from apps.kernel.finance.models import LedgerEntry
from apps.kernel.tenancy.services import is_institute_admin, user_has_role

from .models import Certificate, Course, CourseSession, Enrollment, SessionProgress
from .signals import certificate_issued, enrollment_cancelled, enrollment_confirmed

HOLD_MINUTES = 15
CANCEL_FULL_REFUND_HOURS = 24


class CourseError(Exception):
    def __init__(self, message: str, *, code: str = "workshop_error", extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.extra = extra or {}


def _lms_settings(course: Course) -> dict:
    modules = (course.institute.settings or {}).get("modules") or {}
    return modules.get("lms") or {}


def _hold_minutes(course: Course) -> int:
    raw = _lms_settings(course).get("hold_minutes")
    return HOLD_MINUTES if raw is None else int(raw)


def _refund_window_hours(course: Course) -> int:
    raw = _lms_settings(course).get("refund_window_hours")
    return CANCEL_FULL_REFUND_HOURS if raw is None else int(raw)


def _occupying_q(*, now=None):
    now = now or timezone.now()
    return Q(status=Enrollment.Status.ACTIVE) | Q(
        status=Enrollment.Status.PENDING_PAYMENT,
        hold_expires_at__gt=now,
    )


def occupied_seats(course: Course, *, now=None) -> int:
    return Enrollment.objects.filter(workshop=course).filter(_occupying_q(now=now)).count()


def seats_remaining(course: Course, *, now=None) -> int:
    return max(0, course.capacity - occupied_seats(course, now=now))


def _hold_still_valid(enrollment: Enrollment, now) -> bool:
    return (
        enrollment.status == Enrollment.Status.PENDING_PAYMENT
        and enrollment.hold_expires_at is not None
        and enrollment.hold_expires_at > now
    )


@transaction.atomic
def enroll(*, course: Course, user) -> Enrollment:
    """Hold a seat. A free course activates immediately."""
    course = Course.objects.select_for_update().get(pk=course.pk)
    now = timezone.now()
    enrollment = (
        Enrollment.objects.select_for_update().filter(workshop=course, user=user).first()
    )
    if enrollment and enrollment.status == Enrollment.Status.ACTIVE:
        raise CourseError("Already enrolled.", code="already_enrolled")
    if enrollment and _hold_still_valid(enrollment, now):
        return enrollment

    occupied = occupied_seats(course, now=now)
    if occupied >= course.capacity:
        raise CourseError("Workshop is full.", code="workshop_full")

    price = Decimal(course.price)
    hold_until = now + timedelta(minutes=_hold_minutes(course))
    if enrollment:
        enrollment.status = Enrollment.Status.PENDING_PAYMENT
        enrollment.price_snapshot = price
        enrollment.hold_expires_at = hold_until
        enrollment.payment_ref = ""
        enrollment.deposit_ledger_ref = ""
        enrollment.refund_ledger_ref = ""
        enrollment.canceled_at = None
        enrollment.cancellation_reason = ""
        enrollment.save()
    else:
        enrollment = Enrollment.objects.create(
            workshop=course,
            user=user,
            institute=course.institute,
            status=Enrollment.Status.PENDING_PAYMENT,
            price_snapshot=price,
            hold_expires_at=hold_until,
        )

    if price == 0:
        enrollment.status = Enrollment.Status.ACTIVE
        enrollment.hold_expires_at = None
        enrollment.payment_ref = "free"
        enrollment.save(update_fields=["status", "hold_expires_at", "payment_ref", "updated_at"])
        enrollment_confirmed.send(sender=Enrollment, enrollment=enrollment)
    return enrollment


@transaction.atomic
def confirm_enrollment(*, enrollment: Enrollment, payment_ref: str, idempotency_key: str) -> Enrollment:
    enrollment = (
        Enrollment.objects.select_for_update()
        .select_related("user", "workshop", "workshop__institute")
        .get(pk=enrollment.pk)
    )
    now = timezone.now()
    if enrollment.status == Enrollment.Status.ACTIVE:
        return enrollment
    if enrollment.status != Enrollment.Status.PENDING_PAYMENT:
        raise CourseError("Enrollment is not awaiting payment.", code="invalid_status")
    if enrollment.hold_expires_at and enrollment.hold_expires_at < now:
        raise CourseError("Hold expired. Please register again.", code="hold_expired")

    amount = Decimal(enrollment.price_snapshot)
    course = enrollment.workshop
    if amount == 0:
        enrollment.status = Enrollment.Status.ACTIVE
        enrollment.hold_expires_at = None
        enrollment.payment_ref = payment_ref or "free"
        enrollment.save(update_fields=["status", "hold_expires_at", "payment_ref", "updated_at"])
        enrollment_confirmed.send(sender=Enrollment, enrollment=enrollment)
        return enrollment

    try:
        entry = finance_services.debit_wallet(
            user=enrollment.user,
            amount=amount,
            entry_type=LedgerEntry.EntryType.WORKSHOP_PURCHASE,
            idempotency_key=idempotency_key,
            reference=f"lms.course:{course.pk}",
            description=course.title,
            institute=course.institute,
        )
    except finance_services.InsufficientFunds as exc:
        wallet = finance_services.get_or_create_wallet(enrollment.user)
        raise CourseError(
            str(exc),
            code="insufficient_funds",
            extra={
                "required": str(amount),
                "balance": str(wallet.balance),
                "shortfall": str(max(Decimal("0"), amount - wallet.balance)),
            },
        ) from exc

    enrollment.status = Enrollment.Status.ACTIVE
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
    enrollment_confirmed.send(sender=Enrollment, enrollment=enrollment)
    return enrollment


@transaction.atomic
def cancel_enrollment(*, enrollment: Enrollment, canceled_by: str, reason: str = "") -> Enrollment:
    enrollment = (
        Enrollment.objects.select_for_update()
        .select_related("user", "workshop", "workshop__institute")
        .get(pk=enrollment.pk)
    )
    if enrollment.status not in (Enrollment.Status.PENDING_PAYMENT, Enrollment.Status.ACTIVE):
        raise CourseError("Enrollment cannot be canceled.", code="invalid_status")

    now = timezone.now()
    refund = False
    course = enrollment.workshop
    if enrollment.status == Enrollment.Status.PENDING_PAYMENT:
        new_status = Enrollment.Status.CANCELED
    elif canceled_by == "admin":
        new_status = Enrollment.Status.REFUNDED
        refund = Decimal(enrollment.price_snapshot) > 0
    elif canceled_by == "patient":
        starts = course.starts_at
        window = timedelta(hours=_refund_window_hours(course))
        if Decimal(enrollment.price_snapshot) > 0 and starts and starts - now > window:
            new_status = Enrollment.Status.REFUNDED
            refund = True
        else:
            new_status = Enrollment.Status.CANCELED
            refund = False
    else:
        raise CourseError("Invalid canceled_by.", code="invalid_actor")

    refund_ref = ""
    if refund:
        entry = finance_services.credit_wallet(
            user=enrollment.user,
            amount=Decimal(enrollment.price_snapshot),
            entry_type=LedgerEntry.EntryType.REFUND,
            idempotency_key=f"workshop-refund:{enrollment.pk}",
            reference=f"lms.course:{course.pk}",
            description="Workshop enrollment refund",
            institute=course.institute,
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
    enrollment_cancelled.send(sender=Enrollment, enrollment=enrollment)
    return enrollment


def viewer_has_content_access(*, user, course: Course) -> bool:
    if not user or not user.is_authenticated:
        return False
    slug = course.institute.slug
    if is_institute_admin(user, slug):
        return True
    if course.instructor_id == user.id and user_has_role(user, slug, "staff"):
        return True
    return Enrollment.objects.filter(
        workshop=course,
        user=user,
        status=Enrollment.Status.ACTIVE,
    ).exists()


def get_active_enrollment(*, user, course: Course) -> Enrollment | None:
    if not user or not user.is_authenticated:
        return None
    return Enrollment.objects.filter(
        workshop=course,
        user=user,
        status=Enrollment.Status.ACTIVE,
    ).first()


def progress_percent(*, enrollment: Enrollment | None, course: Course) -> int | None:
    total = course.sessions.count()
    if enrollment is None:
        return None
    if total == 0:
        return 0
    done = SessionProgress.objects.filter(enrollment=enrollment, session__workshop=course).count()
    return round(100 * done / total)


def mark_session_complete(*, enrollment: Enrollment, session: CourseSession) -> SessionProgress:
    if enrollment.status != Enrollment.Status.ACTIVE:
        raise CourseError("Active enrollment required.", code="forbidden")
    if session.workshop_id != enrollment.workshop_id:
        raise CourseError("Session does not belong to this workshop.", code="invalid_session")
    progress, _ = SessionProgress.objects.get_or_create(enrollment=enrollment, session=session)
    return progress


def issue_certificate(*, enrollment: Enrollment) -> Certificate:
    if enrollment.status != Enrollment.Status.ACTIVE:
        raise CourseError("Active enrollment required.", code="forbidden")
    course = enrollment.workshop
    if not course.certificate_enabled:
        raise CourseError("Certificates are not enabled.", code="cert_disabled")
    total = course.sessions.count()
    if total < 1:
        raise CourseError("Workshop has no sessions to complete.", code="no_sessions")
    done = SessionProgress.objects.filter(enrollment=enrollment, session__workshop=course).count()
    if done < total:
        raise CourseError(
            "Complete all sessions before issuing a certificate.",
            code="incomplete",
            extra={"progress_percent": round(100 * done / total)},
        )
    existing = Certificate.objects.filter(enrollment=enrollment).first()
    if existing:
        return existing
    prefix = course.institute.slug.upper()
    code = f"{prefix}-WS-{enrollment.pk}-{secrets.token_hex(4).upper()}"
    certificate = Certificate.objects.create(enrollment=enrollment, certificate_code=code)
    certificate_issued.send(sender=Certificate, certificate=certificate)
    return certificate
