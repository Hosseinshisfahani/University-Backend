"""Psychology adapters over booking leave."""

from apps.modules.booking.services.leave import (
    LeaveError,
    approve_leave_request,
    cancel_leave_request,
    overlapping_appointments,
    reject_leave_request,
    submit_leave_request as _submit,
)


def submit_leave_request(*, therapist, starts_on, ends_on, reason, start_time=None, end_time=None):
    if therapist.provider_id is None:
        raise LeaveError("This therapist has no booking provider.")
    return _submit(
        provider=therapist.provider,
        starts_on=starts_on,
        ends_on=ends_on,
        reason=reason,
        start_time=start_time,
        end_time=end_time,
    )
