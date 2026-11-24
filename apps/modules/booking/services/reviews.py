"""Eligibility for a review of one completed appointment."""

from __future__ import annotations

from django.db import transaction

from apps.modules.reviews.models import Review
from apps.modules.reviews.services import ReviewsError, record_review

from ..models import Appointment, AppointmentReview


class ReviewError(Exception):
    pass


@transaction.atomic
def submit_appointment_review(*, appointment: Appointment, customer, rating: int, body: str = "") -> Review:
    appointment = Appointment.objects.select_for_update().select_related("provider", "institute").get(
        pk=appointment.pk
    )
    if appointment.customer_id != customer.id:
        raise ReviewError("You can only review your own appointments.")
    if appointment.status != Appointment.Status.COMPLETED:
        raise ReviewError("Only completed appointments can be reviewed.")
    if AppointmentReview.objects.filter(appointment=appointment).exists():
        raise ReviewError("This appointment already has a review.")
    if appointment.provider_id is None:
        raise ReviewError("This appointment has no provider.")
    try:
        review = record_review(
            institute=appointment.institute,
            author=customer,
            target=appointment.provider,
            rating=rating,
            body=body,
        )
    except ReviewsError as exc:
        raise ReviewError(str(exc)) from exc
    AppointmentReview.objects.create(
        review=review,
        appointment=appointment,
        customer=customer,
        institute=appointment.institute,
    )
    return review
