"""Patient-to-therapist ratings and admin comment moderation."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from ..models import Appointment, PatientProfile, TherapistReview


class ReviewError(Exception):
    pass


def _text_status_for_body(body: str) -> str:
    return (
        TherapistReview.TextStatus.PENDING
        if body
        else TherapistReview.TextStatus.NONE
    )


@transaction.atomic
def create_review(
    *,
    appointment: Appointment,
    patient: PatientProfile,
    rating: int,
    body: str = "",
) -> TherapistReview:
    appointment = Appointment.objects.select_for_update().select_related(
        "patient", "therapist"
    ).get(pk=appointment.pk)
    if appointment.patient_id != patient.id:
        raise ReviewError("You can only review your own appointments.")
    if appointment.status != Appointment.Status.COMPLETED:
        raise ReviewError("Only completed appointments can be reviewed.")
    if TherapistReview.objects.filter(appointment=appointment).exists():
        raise ReviewError("This appointment already has a review.")
    if rating < 1 or rating > 5:
        raise ReviewError("Rating must be between 1 and 5.")

    text = (body or "").strip()
    return TherapistReview.objects.create(
        appointment=appointment,
        patient=appointment.patient,
        therapist=appointment.therapist,
        rating=rating,
        body=text,
        text_status=_text_status_for_body(text),
    )


@transaction.atomic
def approve_review(
    *,
    review: TherapistReview,
    reviewer,
    admin_note: str = "",
) -> TherapistReview:
    review = TherapistReview.objects.select_for_update().get(pk=review.pk)
    if review.text_status != TherapistReview.TextStatus.PENDING:
        raise ReviewError("Only pending comments can be approved.")
    if not review.body.strip():
        raise ReviewError("No comment to approve.")
    review.text_status = TherapistReview.TextStatus.APPROVED
    review.reviewed_by = reviewer
    review.reviewed_at = timezone.now()
    review.admin_note = (admin_note or "").strip()
    review.save(
        update_fields=[
            "text_status",
            "reviewed_by",
            "reviewed_at",
            "admin_note",
            "updated_at",
        ]
    )
    return review


@transaction.atomic
def reject_review(
    *,
    review: TherapistReview,
    reviewer,
    admin_note: str = "",
) -> TherapistReview:
    review = TherapistReview.objects.select_for_update().get(pk=review.pk)
    if review.text_status != TherapistReview.TextStatus.PENDING:
        raise ReviewError("Only pending comments can be rejected.")
    review.text_status = TherapistReview.TextStatus.REJECTED
    review.reviewed_by = reviewer
    review.reviewed_at = timezone.now()
    review.admin_note = (admin_note or "").strip()
    review.save(
        update_fields=[
            "text_status",
            "reviewed_by",
            "reviewed_at",
            "admin_note",
            "updated_at",
        ]
    )
    return review
