from django.conf import settings
from django.db import models

from apps.kernel.core.storage import private_media_storage
from apps.kernel.tenancy.models import InstituteScopedModel


def banner_upload(instance, filename: str) -> str:
    return f"lms/{instance.institute.slug}/banners/{filename}"


def certificate_upload(instance, filename: str) -> str:
    slug = instance.enrollment.workshop.institute.slug
    return f"lms/{slug}/certificates/{filename}"


class Course(InstituteScopedModel):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=50)
    description = models.TextField(blank=True)
    body_md = models.TextField(blank=True)
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lms_courses",
    )
    capacity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=12, decimal_places=0)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    banner_image = models.ImageField(upload_to=banner_upload, blank=True, max_length=500)
    recording_url = models.URLField(blank=True)
    is_published = models.BooleanField(default=False)
    certificate_enabled = models.BooleanField(default=False)

    class Meta:
        ordering = ["-starts_at", "title"]
        verbose_name = "دوره"
        verbose_name_plural = "دوره‌ها"
        constraints = [
            models.UniqueConstraint(fields=["institute", "slug"], name="uniq_lms_course_slug"),
        ]

    def __str__(self) -> str:
        return self.title


class Enrollment(InstituteScopedModel):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Pending payment"
        ACTIVE = "active", "Active"
        CANCELED = "canceled", "Canceled"
        REFUNDED = "refunded", "Refunded"

    workshop = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="enrollments")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lms_enrollments",
    )
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING_PAYMENT)
    price_snapshot = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    hold_expires_at = models.DateTimeField(null=True, blank=True)
    payment_ref = models.CharField(max_length=64, blank=True)
    gateway_payment_id = models.PositiveIntegerField(null=True, blank=True)
    deposit_ledger_ref = models.CharField(max_length=64, blank=True)
    refund_ledger_ref = models.CharField(max_length=64, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["workshop", "user"], name="uniq_lms_enrollment_user"),
        ]
        ordering = ["-enrolled_at"]
        verbose_name = "ثبت‌نام دوره"
        verbose_name_plural = "ثبت‌نام‌های دوره"

    def __str__(self) -> str:
        return f"{self.user_id} @ {self.workshop_id}"

    def save(self, *args, **kwargs):
        if self.workshop_id and not self.institute_id:
            self.institute_id = self.workshop.institute_id
        super().save(*args, **kwargs)


class CourseSession(InstituteScopedModel):
    workshop = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="sessions")
    sort_order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=200)
    summary = models.TextField(blank=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    meeting_url = models.URLField(blank=True, max_length=500)
    recording_url = models.URLField(blank=True, max_length=500)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "جلسه دوره"
        verbose_name_plural = "جلسه‌های دوره"

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs):
        if self.workshop_id and not self.institute_id:
            self.institute_id = self.workshop.institute_id
        super().save(*args, **kwargs)


class CourseResource(InstituteScopedModel):
    class Kind(models.TextChoices):
        PDF = "pdf", "PDF"
        SLIDES = "slides", "Slides"
        OTHER = "other", "Other"

    workshop = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="resources")
    session = models.ForeignKey(
        CourseSession,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="resources",
    )
    sort_order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.OTHER)
    file_url = models.URLField(blank=True, max_length=500)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "منبع دوره"
        verbose_name_plural = "منابع دوره"

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs):
        if self.workshop_id and not self.institute_id:
            self.institute_id = self.workshop.institute_id
        super().save(*args, **kwargs)


class SessionProgress(models.Model):
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name="session_progress")
    session = models.ForeignKey(CourseSession, on_delete=models.CASCADE, related_name="progress_rows")
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["enrollment", "session"], name="uniq_lms_progress"),
        ]
        verbose_name = "پیشرفت جلسه"
        verbose_name_plural = "پیشرفت جلسه‌ها"

    def __str__(self) -> str:
        return f"{self.enrollment_id}:{self.session_id}"


class Certificate(models.Model):
    enrollment = models.OneToOneField(Enrollment, on_delete=models.CASCADE, related_name="certificate")
    issued_at = models.DateTimeField(auto_now_add=True)
    certificate_code = models.CharField(max_length=64, unique=True)
    file = models.FileField(
        upload_to=certificate_upload,
        storage=private_media_storage,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "گواهی دوره"
        verbose_name_plural = "گواهی‌های دوره"

    def __str__(self) -> str:
        return self.certificate_code
