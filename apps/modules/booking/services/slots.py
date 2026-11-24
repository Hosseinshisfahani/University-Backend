"""Generate open slots from a provider's availability."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from ..models import Appointment, AvailabilityException, Provider, ProviderAvailability, ProviderServiceOffer, Slot

DEFAULT_SLOT_MINUTES = 45

_TERMINAL = (
    Appointment.Status.CANCELED_BY_PATIENT,
    Appointment.Status.CANCELED_BY_THERAPIST,
    Appointment.Status.CANCELED_BY_ADMIN,
    Appointment.Status.COMPLETED,
    Appointment.Status.NO_SHOW,
)


class SlotError(Exception):
    pass


def _bounds(day: date, tz: ZoneInfo, start_t, end_t):
    return datetime.combine(day, start_t, tzinfo=tz), datetime.combine(day, end_t, tzinfo=tz)


def _exceptions_for_day(exceptions, day):
    return [item for item in exceptions if item.date == day]


def _subtract(start, end, blocks):
    segments = [(start, end)]
    for block_start, block_end in blocks:
        next_segments = []
        for seg_start, seg_end in segments:
            if block_end <= seg_start or block_start >= seg_end:
                next_segments.append((seg_start, seg_end))
                continue
            if block_start > seg_start:
                next_segments.append((seg_start, block_start))
            if block_end < seg_end:
                next_segments.append((block_end, seg_end))
        segments = next_segments
    return segments


def _inventory_step(provider: Provider):
    durations = []
    buffers = []
    offers = ProviderServiceOffer.objects.filter(
        provider=provider, is_active=True, service_type__is_active=True
    ).select_related("service_type")
    for offer in offers:
        durations.append(offer.service_type.duration_minutes)
        buffers.append(offer.service_type.buffer_minutes)
    block = max(durations) if durations else DEFAULT_SLOT_MINUTES
    buffer = max(buffers) if buffers else 0
    duration = timedelta(minutes=block)
    return duration, duration + timedelta(minutes=buffer)


@transaction.atomic
def regenerate_slots_for_provider(*, provider: Provider, range_start: date, range_end: date) -> int:
    if range_end < range_start:
        raise ValueError("range_end must be >= range_start")

    batch = uuid.uuid4()
    duration, step = _inventory_step(provider)
    availabilities = list(ProviderAvailability.objects.filter(provider=provider, is_active=True))
    exceptions = list(
        AvailabilityException.objects.filter(provider=provider, date__gte=range_start, date__lte=range_end)
    )
    desired: set[tuple[datetime, datetime]] = set()
    day = range_start
    while day <= range_end:
        if any(item.is_day_off for item in _exceptions_for_day(exceptions, day)):
            day += timedelta(days=1)
            continue
        for window in (item for item in availabilities if item.weekday == day.weekday()):
            if day < window.valid_from or (window.valid_until and day > window.valid_until):
                continue
            tz = ZoneInfo(window.timezone)
            window_start, window_end = _bounds(day, tz, window.start_time, window.end_time)
            blocks = []
            for item in _exceptions_for_day(exceptions, day):
                if item.is_day_off or not item.start_time or not item.end_time:
                    continue
                blocks.append(_bounds(day, tz, item.start_time, item.end_time))
            for seg_start, seg_end in _subtract(window_start, window_end, blocks):
                cursor = seg_start
                while cursor + duration <= seg_end:
                    desired.add((cursor, cursor + duration))
                    cursor = cursor + step
        day += timedelta(days=1)

    range_start_dt = timezone.make_aware(datetime.combine(range_start, datetime.min.time()))
    range_end_dt = timezone.make_aware(datetime.combine(range_end + timedelta(days=1), datetime.min.time()))
    existing_open = Slot.objects.filter(
        provider=provider,
        status=Slot.Status.OPEN,
        starts_at__gte=range_start_dt,
        starts_at__lt=range_end_dt,
    )
    for slot in existing_open.filter(appointment__isnull=False):
        slot.status = Slot.Status.BLOCKED
        slot.hold_expires_at = None
        slot.save(update_fields=["status", "hold_expires_at", "updated_at"])
    for slot in existing_open.filter(appointment__isnull=True):
        key = (slot.starts_at, slot.ends_at)
        if key not in desired:
            try:
                slot.delete()
            except ProtectedError:
                slot.status = Slot.Status.BLOCKED
                slot.hold_expires_at = None
                slot.save(update_fields=["status", "hold_expires_at", "updated_at"])
        else:
            if slot.service_type_id is not None:
                slot.service_type = None
                slot.save(update_fields=["service_type", "updated_at"])
            desired.discard(key)

    created = 0
    for starts_at, ends_at in desired:
        conflict = (
            Slot.objects.filter(
                provider=provider,
                status__in=[Slot.Status.HELD, Slot.Status.BOOKED, Slot.Status.BLOCKED],
                starts_at__lt=ends_at,
                ends_at__gt=starts_at,
            )
            .exclude(appointment__status__in=_TERMINAL)
            .exists()
        )
        if conflict:
            continue
        Slot.objects.create(
            provider=provider,
            service_type=None,
            starts_at=starts_at,
            ends_at=ends_at,
            status=Slot.Status.OPEN,
            generation_batch=batch,
            institute_id=provider.institute_id,
        )
        created += 1
    return created


def slot_window_conflicts(*, provider: Provider, starts_at, ends_at, exclude_pk: int | None = None) -> bool:
    qs = Slot.objects.filter(provider=provider, starts_at__lt=ends_at, ends_at__gt=starts_at)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    if qs.filter(status__in=[Slot.Status.OPEN, Slot.Status.HELD, Slot.Status.BOOKED]).exists():
        return True
    return qs.filter(status=Slot.Status.BLOCKED).exclude(appointment__status__in=_TERMINAL).exists()


@transaction.atomic
def create_open_slot(*, provider: Provider, starts_at, ends_at) -> Slot:
    if ends_at <= starts_at:
        raise SlotError("Slot end must be after start.")
    if slot_window_conflicts(provider=provider, starts_at=starts_at, ends_at=ends_at):
        raise SlotError("Slot overlaps an existing booking or open time.")
    return Slot.objects.create(
        provider=provider,
        service_type=None,
        starts_at=starts_at,
        ends_at=ends_at,
        status=Slot.Status.OPEN,
        institute_id=provider.institute_id,
    )


@transaction.atomic
def delete_open_slot(*, slot: Slot) -> None:
    slot = Slot.objects.select_for_update().get(pk=slot.pk)
    if slot.status != Slot.Status.OPEN or Appointment.objects.filter(slot=slot).exists():
        raise SlotError("Only open slots can be deleted.")
    slot.delete()
