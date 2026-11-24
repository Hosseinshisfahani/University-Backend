"""Psychology review adapter. Eligibility lives on booking.AppointmentReview."""

from __future__ import annotations

from django.db import transaction

from apps.modules.booking.services.reviews import ReviewError as BookingReviewError
from apps.modules.booking.services.reviews import submit_appointment_review
from apps.modules.reviews.models import Review
from apps.modules.reviews.services import ReviewsError, moderate_review

from ..models import PsyReviewContext


class ReviewError(Exception):
    pass


def psy_reviews():
    return Review.objects.filter(appointment_link__isnull=False).select_related(
        "psy_context__patient__user",
        "psy_context__appointment",
        "appointment_link__appointment",
        "author",
    )


@transaction.atomic
def create_review(*, appointment, patient, rating: int, body: str = "") -> Review:
    try:
        review = submit_appointment_review(
            appointment=appointment,
            customer=patient.user,
            rating=rating,
            body=body,
        )
    except BookingReviewError as exc:
        raise ReviewError(str(exc)) from exc
    PsyReviewContext.objects.get_or_create(
        review=review,
        defaults={"appointment": appointment, "patient": patient, "institute_id": appointment.institute_id},
    )
    return review


def _moderate(review, reviewer, admin_note, status, verb):
    try:
        return moderate_review(review=review, status=status, reviewer=reviewer, admin_note=admin_note)
    except ReviewsError as exc:
        message = str(exc)
        if message == "Only pending comments can be moderated.":
            message = f"Only pending comments can be {verb}."
        raise ReviewError(message) from exc


@transaction.atomic
def approve_review(*, review: Review, reviewer, admin_note: str = "") -> Review:
    return _moderate(review, reviewer, admin_note, Review.TextStatus.APPROVED, "approved")


@transaction.atomic
def reject_review(*, review: Review, reviewer, admin_note: str = "") -> Review:
    return _moderate(review, reviewer, admin_note, Review.TextStatus.REJECTED, "rejected")
