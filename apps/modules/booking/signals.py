"""Booking events. Institutes listen; the module never imports an institute."""

from django.dispatch import Signal

appointment_booked = Signal()
appointment_confirmed = Signal()
appointment_cancelled = Signal()
appointment_completed = Signal()
appointment_moved = Signal()
leave_decided = Signal()
