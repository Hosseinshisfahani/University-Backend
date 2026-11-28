from django.conf import settings
from django.db import models

from apps.kernel.tenancy.models import InstituteScopedModel


class Form(InstituteScopedModel):
    title = models.CharField(max_length=200, verbose_name="عنوان")
    slug = models.SlugField(max_length=50, verbose_name="شناسه")
    description = models.TextField(blank=True, verbose_name="توضیحات")
    schema = models.JSONField(default=dict, verbose_name="ساختار")
    version = models.PositiveIntegerField(default=1, verbose_name="نسخه")
    is_published = models.BooleanField(default=False, verbose_name="منتشر شده")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="forms_created",
        verbose_name="ایجادکننده",
    )

    class Meta:
        ordering = ["title"]
        constraints = [
            models.UniqueConstraint(fields=["institute", "slug"], name="uniq_form_slug"),
        ]
        verbose_name = "فرم"
        verbose_name_plural = "فرم‌ها"


class FormVersion(models.Model):
    """Frozen schema. A version that already has responses is never rewritten."""

    form = models.ForeignKey(Form, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    schema = models.JSONField(default=dict)
    schema_available = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["form", "version"], name="uniq_form_version"),
        ]


class Response(InstituteScopedModel):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        REVIEWED = "reviewed", "Reviewed"

    form = models.ForeignKey(Form, on_delete=models.PROTECT, related_name="responses")
    version = models.ForeignKey(
        FormVersion, on_delete=models.PROTECT, related_name="responses"
    )
    respondent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="form_responses",
    )
    answers = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.SUBMITTED
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="form_responses_assigned",
    )
    reviewer_notes = models.TextField(blank=True)
    score = models.JSONField(default=dict, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-submitted_at"]
        verbose_name = "پاسخ فرم"
        verbose_name_plural = "پاسخ‌های فرم"
