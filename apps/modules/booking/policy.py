"""Per-institute booking policy. Missing settings keep the historical 24-hour window."""

DEFAULT_CANCEL_WINDOW_HOURS = 24


def booking_settings(institute) -> dict:
    raw = getattr(institute, "settings", None) or {}
    if not isinstance(raw, dict):
        return {}
    booking = raw.get("booking")
    return booking if isinstance(booking, dict) else {}


def cancel_window_hours(institute) -> int:
    try:
        value = int(booking_settings(institute).get("cancel_window_hours", DEFAULT_CANCEL_WINDOW_HOURS))
    except (TypeError, ValueError):
        return DEFAULT_CANCEL_WINDOW_HOURS
    return value if value >= 0 else DEFAULT_CANCEL_WINDOW_HOURS


def refund_on_late_cancel(institute) -> bool:
    return bool(booking_settings(institute).get("refund_on_late_cancel", False))
