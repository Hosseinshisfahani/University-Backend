"""Psychology adapters over the booking module. Callers still pass patient profiles."""

from apps.modules.booking.services.booking import (
    OFFLINE_PAYMENT_REF,
    BookingError,
    admin_book_appointment as _admin_book,
    book_slot as _book_slot,
    cancel_appointment,
    complete_appointment,
    confirm_appointment_payment,
    move_appointment,
)

__all__ = [
    "OFFLINE_PAYMENT_REF",
    "BookingError",
    "admin_book_appointment",
    "book_slot",
    "cancel_appointment",
    "complete_appointment",
    "confirm_appointment_payment",
    "move_appointment",
]


def book_slot(*, patient, slot_id: int, session_type_id: int):
    return _book_slot(customer=patient.user, slot_id=slot_id, service_type_id=session_type_id)


def admin_book_appointment(*, patient, slot_id: int, session_type_id: int, payment: str):
    return _admin_book(
        customer=patient.user,
        slot_id=slot_id,
        service_type_id=session_type_id,
        payment=payment,
    )
