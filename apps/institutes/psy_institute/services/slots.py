"""Generate generic AppointmentSlot time blocks from therapist availability."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from ..models import (
    Appointment,
    AppointmentSlot,
    AvailabilityException,
    TherapistAvailability,
    TherapistProfile,
    TherapistSessionOffer,
)

DEFAULT_SLOT_MINUTES = 45


class SlotError(Exception):
    pass


_TERMINAL_APPOINTMENT_STATUSES = (
    Appointment.Status.CANCELED_BY_PATIENT,
    Appointment.Status.CANCELED_BY_THERAPIST,
    Appointment.Status.CANCELED_BY_ADMIN,
    Appointment.Status.COMPLETED,
    Appointment.Status.NO_SHOW,
)


def _local_day_bounds(d: date, tz: ZoneInfo, start_t, end_t) -> tuple[datetime, datetime]:
    start = datetime.combine(d, start_t, tzinfo=tz)
    end = datetime.combine(d, end_t, tzinfo=tz)
    return start, end


def _exceptions_for_day(exceptions: list[AvailabilityException], d: date) -> list[AvailabilityException]:
    return [e for e in exceptions if e.date == d]


def _window_blocked(exceptions: list[AvailabilityException], d: date) -> bool:
    return any(e.is_day_off for e in _exceptions_for_day(exceptions, d))


def _partial_blocks(
    exceptions: list[AvailabilityException], d: date, tz: ZoneInfo
) -> list[tuple[datetime, datetime]]:
    blocks = []
    for e in _exceptions_for_day(exceptions, d):
        if e.is_day_off or not e.start_time or not e.end_time:
            continue
        blocks.append(_local_day_bounds(d, tz, e.start_time, e.end_time))
    return blocks


def _subtract_blocks(
    start: datetime, end: datetime, blocks: list[tuple[datetime, datetime]]
) -> list[tuple[datetime, datetime]]:
    segments = [(start, end)]
    for b_start, b_end in blocks:
        next_segments = []
        for s, e in segments:
            if b_end <= s or b_start >= e:
                next_segments.append((s, e))
                continue
            if b_start > s:
                next_segments.append((s, b_start))
            if b_end < e:
                next_segments.append((b_end, e))
        segments = next_segments
    return segments


def _inventory_step(therapist: TherapistProfile) -> tuple[timedelta, timedelta]:
    """One generic block length for this therapist's open inventory."""
    durations: list[int] = []
    buffers: list[int] = []
    for offer in TherapistSessionOffer.objects.filter(
        therapist=therapist, is_active=True, session_type__is_active=True
    ).select_related("session_type"):
        durations.append(offer.session_type.duration_minutes)
        buffers.append(offer.session_type.buffer_minutes)
    block = max(durations) if durations else DEFAULT_SLOT_MINUTES
    buffer = max(buffers) if buffers else 0
    duration = timedelta(minutes=block)
    return duration, duration + timedelta(minutes=buffer)


@transaction.atomic
def regenerate_slots_for_therapist(
    *,
    therapist: TherapistProfile,
    range_start: date,
    range_end: date,
) -> int:
    """
    Materialize generic open time blocks for [range_start, range_end] inclusive.
    Does not stamp SessionType onto open slots. Does not modify booked/held
    slots. Deletes obsolete open slots in range that are no longer generated.
    Slots still referenced by an appointment (including canceled ones) are
    never deleted: they are archived as blocked so a fresh open slot can
    be created for the same window.
    """
    if range_end < range_start:
        raise ValueError("range_end must be >= range_start")

    batch = uuid.uuid4()
    duration, step = _inventory_step(therapist)
    availabilities = list(
        TherapistAvailability.objects.filter(therapist=therapist, is_active=True)
    )
    exceptions = list(
        AvailabilityException.objects.filter(
            therapist=therapist,
            date__gte=range_start,
            date__lte=range_end,
        )
    )

    desired: set[tuple[datetime, datetime]] = set()

    day = range_start
    while day <= range_end:
        if _window_blocked(exceptions, day):
            day += timedelta(days=1)
            continue

        weekday = day.weekday()
        day_windows = [a for a in availabilities if a.weekday == weekday]
        for window in day_windows:
            if day < window.valid_from:
                continue
            if window.valid_until and day > window.valid_until:
                continue

            tz = ZoneInfo(window.timezone)
            w_start, w_end = _local_day_bounds(day, tz, window.start_time, window.end_time)
            blocks = _partial_blocks(exceptions, day, tz)
            segments = _subtract_blocks(w_start, w_end, blocks)

            for seg_start, seg_end in segments:
                cursor = seg_start
                while cursor + duration <= seg_end:
                    slot_end = cursor + duration
                    desired.add((cursor, slot_end))
                    cursor = cursor + step

        day += timedelta(days=1)

    range_start_dt = timezone.make_aware(
        datetime.combine(range_start, datetime.min.time())
    )
    range_end_dt = timezone.make_aware(
        datetime.combine(range_end + timedelta(days=1), datetime.min.time())
    )

    existing_open = AppointmentSlot.objects.filter(
        therapist=therapist,
        status=AppointmentSlot.Status.OPEN,
        starts_at__gte=range_start_dt,
        starts_at__lt=range_end_dt,
    )
    for slot in existing_open.filter(appointment__isnull=False):
        slot.status = AppointmentSlot.Status.BLOCKED
        slot.hold_expires_at = None
        slot.save(update_fields=["status", "hold_expires_at", "updated_at"])

    for slot in existing_open.filter(appointment__isnull=True):
        key = (slot.starts_at, slot.ends_at)
        if key not in desired:
            try:
                slot.delete()
            except ProtectedError:
                slot.status = AppointmentSlot.Status.BLOCKED
                slot.hold_expires_at = None
                slot.save(update_fields=["status", "hold_expires_at", "updated_at"])
        else:
            if slot.session_type_id is not None:
                slot.session_type = None
                slot.save(update_fields=["session_type", "updated_at"])
            desired.discard(key)

    created = 0
    for starts_at, ends_at in desired:
        conflict = (
            AppointmentSlot.objects.filter(
                therapist=therapist,
                status__in=[
                    AppointmentSlot.Status.HELD,
                    AppointmentSlot.Status.BOOKED,
                    AppointmentSlot.Status.BLOCKED,
                ],
                starts_at__lt=ends_at,
                ends_at__gt=starts_at,
            )
            .exclude(appointment__status__in=_TERMINAL_APPOINTMENT_STATUSES)
            .exists()
        )
        if conflict:
            continue
        AppointmentSlot.objects.create(
            therapist=therapist,
            session_type=None,
            starts_at=starts_at,
            ends_at=ends_at,
            status=AppointmentSlot.Status.OPEN,
            generation_batch=batch,
        )
        created += 1

    return created


def slot_window_conflicts(
    *,
    therapist: TherapistProfile,
    starts_at: datetime,
    ends_at: datetime,
    exclude_pk: int | None = None,
) -> bool:
    """True if another live slot occupies this window."""
    qs = AppointmentSlot.objects.filter(
        therapist=therapist,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    if qs.filter(
        status__in=[
            AppointmentSlot.Status.OPEN,
            AppointmentSlot.Status.HELD,
            AppointmentSlot.Status.BOOKED,
        ]
    ).exists():
        return True
    return (
        qs.filter(status=AppointmentSlot.Status.BLOCKED)
        .exclude(appointment__status__in=_TERMINAL_APPOINTMENT_STATUSES)
        .exists()
    )


@transaction.atomic
def create_open_slot(
    *,
    therapist: TherapistProfile,
    starts_at: datetime,
    ends_at: datetime,
) -> AppointmentSlot:
    if ends_at <= starts_at:
        raise SlotError("Slot end must be after start.")
    if slot_window_conflicts(
        therapist=therapist, starts_at=starts_at, ends_at=ends_at
    ):
        raise SlotError("Slot overlaps an existing booking or open time.")
    return AppointmentSlot.objects.create(
        therapist=therapist,
        session_type=None,
        starts_at=starts_at,
        ends_at=ends_at,
        status=AppointmentSlot.Status.OPEN,
    )


@transaction.atomic
def delete_open_slot(*, slot: AppointmentSlot) -> None:
    slot = AppointmentSlot.objects.select_for_update().get(pk=slot.pk)
    if slot.status != AppointmentSlot.Status.OPEN:
        raise SlotError("Only open slots can be deleted.")
    if Appointment.objects.filter(slot=slot).exists():
        raise SlotError("Slot is attached to an appointment.")
    slot.delete()
