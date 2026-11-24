from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.kernel.tenancy.models import InstituteScopedModel


class Review(InstituteScopedModel):
    """A rating of one registered target inside an institute.

    Comment text is public only after moderation marks it approved.
    The target kind is limited by the service; callers never send a raw
    content-type id.
    """

    class TextStatus(models.TextChoices):
        NONE = "none", "No text"
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviews_authored",
        verbose_name="نویسنده",
    )
    target_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    target_id = models.PositiveIntegerField()
    target = GenericForeignKey("target_type", "target_id")
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name="امتیاز",
    )
    body = models.TextField(blank=True, verbose_name="متن نظر")
    text_status = models.CharField(
        max_length=16,
        choices=TextStatus.choices,
        default=TextStatus.NONE,
        db_index=True,
        verbose_name="وضعیت متن",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews_moderated",
        verbose_name="بررسی‌کننده",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name="تاریخ بررسی")
    admin_note = models.TextField(blank=True, verbose_name="یادداشت مدیر")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["institute", "target_type", "target_id"]),
        ]
        verbose_name = "نظر"
        verbose_name_plural = "نظرات"
