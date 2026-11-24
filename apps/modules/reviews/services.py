from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from apps.kernel.tenancy.models import Institute

from .models import Review


class ReviewsError(Exception):
    pass


def record_review(
    *,
    institute: Institute,
    author,
    target,
    rating: int,
    body: str = "",
    text_status: str | None = None,
    reviewed_by=None,
    reviewed_at=None,
    admin_note: str = "",
) -> Review:
    """Create one review. The target must already belong to this institute."""
    if getattr(target, "institute_id", None) != institute.id:
        raise ReviewsError("هدف متعلق به این مرکز نیست.")
    if rating < 1 or rating > 5:
        raise ReviewsError("امتیاز باید بین ۱ و ۵ باشد.")
    text = (body or "").strip()
    status = text_status or (
        Review.TextStatus.PENDING if text else Review.TextStatus.NONE
    )
    return Review.objects.create(
        institute=institute,
        author=author,
        target=target,
        rating=rating,
        body=text,
        text_status=status,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        admin_note=(admin_note or "").strip(),
    )


@transaction.atomic
def moderate_review(*, review: Review, status: str, reviewer, admin_note: str = "") -> Review:
    review = Review.objects.select_for_update().get(pk=review.pk)
    if review.text_status != Review.TextStatus.PENDING:
        raise ReviewsError("Only pending comments can be moderated.")
    if status == Review.TextStatus.APPROVED and not review.body.strip():
        raise ReviewsError("No comment to approve.")
    if status not in {Review.TextStatus.APPROVED, Review.TextStatus.REJECTED}:
        raise ReviewsError("وضعیت نامعتبر است.")
    review.text_status = status
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


def reviews_for_target(institute: Institute, target):
    content_type = ContentType.objects.get_for_model(target)
    return Review.objects.filter(
        institute=institute,
        target_type=content_type,
        target_id=target.pk,
    )
