"""Psychology adapters over booking slot generation."""

from apps.modules.booking.services.slots import (
    SlotError,
    create_open_slot as _create_open_slot,
    delete_open_slot,
    regenerate_slots_for_provider,
)


def regenerate_slots_for_therapist(*, therapist, range_start, range_end) -> int:
    if therapist.provider_id is None:
        raise SlotError("This therapist has no booking provider.")
    return regenerate_slots_for_provider(
        provider=therapist.provider, range_start=range_start, range_end=range_end
    )


def create_open_slot(*, therapist, starts_at, ends_at):
    if therapist.provider_id is None:
        raise SlotError("This therapist has no booking provider.")
    return _create_open_slot(provider=therapist.provider, starts_at=starts_at, ends_at=ends_at)
