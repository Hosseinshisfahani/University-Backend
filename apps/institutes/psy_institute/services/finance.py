"""Read-only earnings reports scoped to a single therapist.

Clinic-wide ledger / SEP totals stay on the admin finance API.
This module only sums ``Appointment.price_snapshot`` for the calling
therapist's own paid sessions.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from ..models import Appointment, AppointmentSlot, TherapistProfile

# Paid, non-canceled states that count toward therapist earnings.
# pending_payment, canceled_*, and no_show are excluded.
EARNED_STATUSES = (
    Appointment.Status.CONFIRMED,
    Appointment.Status.COMPLETED,
)

EXCLUDED_STATUSES = (
    Appointment.Status.PENDING_PAYMENT,
    Appointment.Status.CANCELED_BY_PATIENT,
    Appointment.Status.CANCELED_BY_THERAPIST,
    Appointment.Status.CANCELED_BY_ADMIN,
    Appointment.Status.NO_SHOW,
)


def therapist_appointments_qs(therapist: TherapistProfile):
    """Inventory-owned rows only — never another therapist's book."""
    return Appointment.objects.filter(slot__therapist=therapist)


def therapist_finance_report(
    *,
    therapist: TherapistProfile,
    start_date: date,
    end_date: date,
    now: datetime | None = None,
) -> dict:
    """Aggregate this therapist's confirmed/completed snapshots in a range.

    Upcoming potential is confirmed sessions that have not started yet
    and still fall inside the selected window.
    """
    now = now or timezone.now()
    scoped = (
        therapist_appointments_qs(therapist)
        .filter(starts_at__date__gte=start_date, starts_at__date__lte=end_date)
        .exclude(status__in=EXCLUDED_STATUSES)
        .exclude(slot__status=AppointmentSlot.Status.BLOCKED)
        .filter(status__in=EARNED_STATUSES)
    )

    totals = scoped.aggregate(
        total_income=Coalesce(Sum("price_snapshot"), Decimal("0")),
        paid_sessions_count=Count("id"),
        upcoming_potential_revenue=Coalesce(
            Sum(
                "price_snapshot",
                filter=Q(
                    status=Appointment.Status.CONFIRMED,
                    starts_at__gte=now,
                ),
            ),
            Decimal("0"),
        ),
    )

    rows = (
        scoped.select_related("patient__user", "session_type")
        .order_by("-starts_at", "-id")
    )
    appointments = [
        {
            "id": appt.id,
            "starts_at": appt.starts_at,
            "session_type_name": appt.session_type.name,
            "patient_id": appt.patient_id,
            "patient_name": _patient_display_name(appt),
            "amount": appt.price_snapshot,
            "status": appt.status,
        }
        for appt in rows
    ]

    return {
        "start_date": start_date,
        "end_date": end_date,
        "total_income": totals["total_income"],
        "paid_sessions_count": totals["paid_sessions_count"],
        "upcoming_potential_revenue": totals["upcoming_potential_revenue"],
        "appointments": appointments,
    }


def _patient_display_name(appt: Appointment) -> str:
    user = appt.patient.user
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.username
