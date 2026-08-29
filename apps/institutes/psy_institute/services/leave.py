"""Therapist leave requests: submit, cancel, approve, reject."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from ..models import (
    Appointment,
    AvailabilityException,
    LeaveRequest,
    TherapistProfile,
)
from .slots import regenerate_slots_for_therapist

TEHRAN = ZoneInfo("Asia/Tehran")

_ACTIVE_APPOINTMENT_STATUSES = (
    Appointment.Status.PENDING_PAYMENT,
    Appointment.Status.CONFIRMED,
)


class LeaveError(Exception):
    pass


def overlapping_appointments(*, leave: LeaveRequest):
    qs = Appointment.objects.filter(
        therapist=leave.therapist,
        status__in=_ACTIVE_APPOINTMENT_STATUSES,
        starts_at__date__lte=leave.ends_on,
        ends_at__date__gte=leave.starts_on,
    ).select_related("patient__user", "therapist", "session_type", "slot")
    if not (leave.start_time and leave.end_time):
        return list(qs)

    conflicts = []
    for appt in qs:
        cursor = leave.starts_on
        while cursor <= leave.ends_on:
            window_start = datetime.combine(cursor, leave.start_time, tzinfo=TEHRAN)
            window_end = datetime.combine(cursor, leave.end_time, tzinfo=TEHRAN)
            if appt.starts_at < window_end and appt.ends_at > window_start:
                conflicts.append(appt)
                break
            cursor += timedelta(days=1)
    return conflicts


@transaction.atomic
def submit_leave_request(
    *,
    therapist: TherapistProfile,
    starts_on,
    ends_on,
    reason: str,
    start_time: time | None = None,
    end_time: time | None = None,
) -> LeaveRequest:
    if ends_on < starts_on:
        raise LeaveError("Leave end date must be on or after the start date.")
    if bool(start_time) != bool(end_time):
        raise LeaveError("Partial leave requires both start and end times.")
    if start_time and end_time and end_time <= start_time:
        raise LeaveError("Leave end time must be after start time.")
    if not reason.strip():
        raise LeaveError("Reason is required.")
    return LeaveRequest.objects.create(
        therapist=therapist,
        starts_on=starts_on,
        ends_on=ends_on,
        start_time=start_time,
        end_time=end_time,
        reason=reason.strip(),
        status=LeaveRequest.Status.PENDING,
    )


@transaction.atomic
def cancel_leave_request(*, leave: LeaveRequest) -> LeaveRequest:
    leave = LeaveRequest.objects.select_for_update().get(pk=leave.pk)
    if leave.status != LeaveRequest.Status.PENDING:
        raise LeaveError("Only pending leave requests can be canceled.")
    leave.status = LeaveRequest.Status.CANCELED
    leave.save(update_fields=["status", "updated_at"])
    return leave


@transaction.atomic
def reject_leave_request(
    *,
    leave: LeaveRequest,
    reviewer,
    admin_note: str = "",
) -> LeaveRequest:
    leave = LeaveRequest.objects.select_for_update().get(pk=leave.pk)
    if leave.status != LeaveRequest.Status.PENDING:
        raise LeaveError("Only pending leave requests can be rejected.")
    leave.status = LeaveRequest.Status.REJECTED
    leave.reviewed_by = reviewer
    leave.reviewed_at = timezone.now()
    leave.admin_note = admin_note
    leave.save(
        update_fields=["status", "reviewed_by", "reviewed_at", "admin_note", "updated_at"]
    )
    return leave


@transaction.atomic
def approve_leave_request(
    *,
    leave: LeaveRequest,
    reviewer,
    admin_note: str = "",
) -> tuple[LeaveRequest, int, list[Appointment]]:
    """
    Approve leave: materialize AvailabilityException rows, regenerate open
    slots, and return overlapping active appointments (not auto-canceled).
    """
    leave = LeaveRequest.objects.select_for_update().get(pk=leave.pk)
    if leave.status != LeaveRequest.Status.PENDING:
        raise LeaveError("Only pending leave requests can be approved.")

    is_day_off = not (leave.start_time and leave.end_time)
    day = leave.starts_on
    while day <= leave.ends_on:
        AvailabilityException.objects.get_or_create(
            therapist=leave.therapist,
            date=day,
            start_time=None if is_day_off else leave.start_time,
            end_time=None if is_day_off else leave.end_time,
            defaults={
                "is_day_off": is_day_off,
                "reason": leave.reason[:255],
            },
        )
        day += timedelta(days=1)

    created = regenerate_slots_for_therapist(
        therapist=leave.therapist,
        range_start=leave.starts_on,
        range_end=leave.ends_on,
    )
    conflicts = overlapping_appointments(leave=leave)

    leave.status = LeaveRequest.Status.APPROVED
    leave.reviewed_by = reviewer
    leave.reviewed_at = timezone.now()
    leave.admin_note = admin_note
    leave.save(
        update_fields=["status", "reviewed_by", "reviewed_at", "admin_note", "updated_at"]
    )
    return leave, created, conflicts
