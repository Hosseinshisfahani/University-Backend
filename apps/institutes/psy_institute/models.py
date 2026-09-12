"""Psychology institute domain models.

Owns clinic people, schedule inventory, appointments, psychometrics,
workshops, CMS, and support tickets.

Finance is integrated with opaque reference strings (``payment_ref``,
``deposit_ledger_ref``, ``refund_ledger_ref``, ``withdrawal_ref``).
This app never mutates ``Wallet.balance`` — all money movement goes
through ``apps.finance.services``.
"""

from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from apps.core.models import TimeStampedModel


# ===========================================================================
# People
# ===========================================================================


class TherapistProfile(TimeStampedModel):
    """Clinic therapist. One-to-one with the auth user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="therapist_profile",
        verbose_name="کاربر",
    )
    display_name = models.CharField(max_length=120, verbose_name="نام نمایشی")
    bio = models.TextField(blank=True, verbose_name="معرفی")
    specialties = models.JSONField(default=list, blank=True, verbose_name="تخصص‌ها")
    is_accepting_patients = models.BooleanField(
        default=True, verbose_name="پذیرش مراجع"
    )
    is_active = models.BooleanField(default=True, verbose_name="فعال")

    class Meta:
        ordering = ["display_name"]
        verbose_name = "درمانگر"
        verbose_name_plural = "درمانگران"

    def __str__(self) -> str:
        return self.display_name


class PatientProfile(TimeStampedModel):
    """Clinic patient. One-to-one with the auth user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="patient_profile",
        verbose_name="کاربر",
    )
    national_id = models.CharField(
        max_length=20, blank=True, db_index=True, verbose_name="کد ملی"
    )
    phone = models.CharField(max_length=32, blank=True, verbose_name="تلفن")
    birth_date = models.DateField(null=True, blank=True, verbose_name="تاریخ تولد")
    notes_internal = models.TextField(blank=True, verbose_name="یادداشت داخلی")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "مراجع"
        verbose_name_plural = "مراجعان"

    def __str__(self) -> str:
        return f"Patient<{self.user_id}>"


# ===========================================================================
# Session catalog
# ===========================================================================


class SessionType(TimeStampedModel):
    """Bookable session product: modality, duration, and price."""

    class Modality(models.TextChoices):
        ONLINE = "online", "Online"
        IN_PERSON = "in_person", "In person"

    name = models.CharField(max_length=120, verbose_name="نام")
    slug = models.SlugField(unique=True, verbose_name="شناسه")
    modality = models.CharField(
        max_length=16, choices=Modality.choices, verbose_name="شیوه برگزاری"
    )
    duration_minutes = models.PositiveIntegerField(verbose_name="مدت (دقیقه)")
    price = models.DecimalField(
        max_digits=12, decimal_places=0, verbose_name="قیمت"
    )
    buffer_minutes = models.PositiveIntegerField(
        default=0, verbose_name="فاصله بین جلسات"
    )
    is_active = models.BooleanField(default=True, verbose_name="فعال")
    sort_order = models.PositiveIntegerField(default=0, verbose_name="ترتیب")

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "نوع جلسه"
        verbose_name_plural = "انواع جلسه"

    def __str__(self) -> str:
        return self.name


class TherapistSessionOffer(TimeStampedModel):
    """Which session types a therapist is allowed to deliver."""

    therapist = models.ForeignKey(
        TherapistProfile,
        on_delete=models.CASCADE,
        related_name="session_offers",
        verbose_name="درمانگر",
    )
    session_type = models.ForeignKey(
        SessionType,
        on_delete=models.CASCADE,
        related_name="therapist_offers",
        verbose_name="نوع جلسه",
    )
    is_active = models.BooleanField(default=True, verbose_name="فعال")

    class Meta:
        unique_together = ("therapist", "session_type")
        verbose_name = "خدمات درمانگر"
        verbose_name_plural = "خدمات درمانگران"

    def __str__(self) -> str:
        return f"{self.therapist} → {self.session_type}"


# ===========================================================================
# Schedule (admin-managed; see schedule_admin.py)
# ===========================================================================


class TherapistAvailability(TimeStampedModel):
    """Recurring weekly window used to generate open slots.

    ``weekday`` is Python's weekday: 0=Monday … 6=Sunday.
    """

    therapist = models.ForeignKey(
        TherapistProfile,
        on_delete=models.CASCADE,
        related_name="availabilities",
        verbose_name="درمانگر",
    )
    weekday = models.PositiveSmallIntegerField(
        help_text="0=Monday … 6=Sunday (Python weekday).",
        verbose_name="روز هفته",
    )
    start_time = models.TimeField(verbose_name="ساعت شروع")
    end_time = models.TimeField(verbose_name="ساعت پایان")
    timezone = models.CharField(
        max_length=64, default="Asia/Tehran", verbose_name="منطقه زمانی"
    )
    valid_from = models.DateField(verbose_name="معتبر از")
    valid_until = models.DateField(
        null=True, blank=True, verbose_name="معتبر تا"
    )
    is_active = models.BooleanField(default=True, verbose_name="فعال")

    class Meta:
        verbose_name = "زمان‌بندی درمانگر"
        verbose_name_plural = "زمان‌بندی درمانگران"
        constraints = [
            models.CheckConstraint(
                condition=Q(end_time__gt=F("start_time")),
                name="psy_availability_end_after_start",
            ),
            models.UniqueConstraint(
                fields=["therapist", "weekday"],
                name="psy_availability_unique_weekday",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.therapist} wd={self.weekday} {self.start_time}-{self.end_time}"


class AvailabilityException(TimeStampedModel):
    """One-off override of the weekly template (day off or a custom window)."""

    therapist = models.ForeignKey(
        TherapistProfile,
        on_delete=models.CASCADE,
        related_name="availability_exceptions",
        verbose_name="درمانگر",
    )
    date = models.DateField(verbose_name="تاریخ")
    is_day_off = models.BooleanField(default=True, verbose_name="روز تعطیل")
    start_time = models.TimeField(
        null=True, blank=True, verbose_name="ساعت شروع"
    )
    end_time = models.TimeField(
        null=True, blank=True, verbose_name="ساعت پایان"
    )
    reason = models.CharField(max_length=255, blank=True, verbose_name="دلیل")

    class Meta:
        unique_together = ("therapist", "date", "start_time", "end_time")
        verbose_name = "استثنای زمان‌بندی"
        verbose_name_plural = "استثناهای زمان‌بندی"

    def __str__(self) -> str:
        return f"Exception {self.therapist} {self.date}"


class LeaveRequest(TimeStampedModel):
    """Therapist leave. Admin approves; approval may block open slots."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELED = "canceled", "Canceled"

    therapist = models.ForeignKey(
        TherapistProfile,
        on_delete=models.CASCADE,
        related_name="leave_requests",
        verbose_name="درمانگر",
    )
    starts_on = models.DateField(verbose_name="از تاریخ")
    ends_on = models.DateField(verbose_name="تا تاریخ")
    start_time = models.TimeField(
        null=True, blank=True, verbose_name="ساعت شروع"
    )
    end_time = models.TimeField(
        null=True, blank=True, verbose_name="ساعت پایان"
    )
    reason = models.TextField(verbose_name="دلیل")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        verbose_name="وضعیت",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="psy_leave_reviews",
        verbose_name="بررسی‌کننده",
    )
    reviewed_at = models.DateTimeField(
        null=True, blank=True, verbose_name="تاریخ بررسی"
    )
    admin_note = models.TextField(blank=True, verbose_name="یادداشت مدیر")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "درخواست مرخصی"
        verbose_name_plural = "درخواست های مرخصی"
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_on__gte=F("starts_on")),
                name="psy_leave_end_on_or_after_start",
            ),
        ]

    def __str__(self) -> str:
        return f"Leave {self.therapist_id} {self.starts_on}–{self.ends_on} ({self.status})"


class AppointmentSlot(TimeStampedModel):
    """Bookable inventory row generated from availability.

    Open slots leave ``session_type`` null. It is set when the slot is
    held or booked so the same window can serve any offered type.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        HELD = "held", "Held"
        BOOKED = "booked", "Booked"
        BLOCKED = "blocked", "Blocked"

    therapist = models.ForeignKey(
        TherapistProfile,
        on_delete=models.CASCADE,
        related_name="slots",
        verbose_name="درمانگر",
    )
    session_type = models.ForeignKey(
        SessionType,
        on_delete=models.PROTECT,
        related_name="slots",
        null=True,
        blank=True,
        help_text="Null while the slot is open inventory; set when held/booked.",
        verbose_name="نوع جلسه",
    )
    starts_at = models.DateTimeField(db_index=True, verbose_name="شروع")
    ends_at = models.DateTimeField(verbose_name="پایان")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
        verbose_name="وضعیت",
    )
    generation_batch = models.UUIDField(
        null=True, blank=True, verbose_name="دسته تولید"
    )
    hold_expires_at = models.DateTimeField(
        null=True, blank=True, verbose_name="انقضای رزرو موقت"
    )

    class Meta:
        ordering = ["starts_at"]
        verbose_name = "بازه نوبت"
        verbose_name_plural = "بازه های نوبت"
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="psy_slot_end_after_start",
            ),
        ]

    def __str__(self) -> str:
        return f"Slot {self.therapist_id} {self.starts_at} ({self.status})"


# ===========================================================================
# Appointments
# ===========================================================================


class Appointment(TimeStampedModel):
    """A booked slot. Payment/refund refs point into ``apps.finance``."""

    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Pending payment"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELED_BY_PATIENT = "canceled_by_patient", "Canceled by patient"
        CANCELED_BY_THERAPIST = "canceled_by_therapist", "Canceled by therapist"
        CANCELED_BY_ADMIN = "canceled_by_admin", "Canceled by admin"
        COMPLETED = "completed", "Completed"
        NO_SHOW = "no_show", "No show"

    class RefundPolicy(models.TextChoices):
        FULL_REFUND = "full_refund", "Full refund"
        FORFEIT = "forfeit", "Forfeit"
        NONE = "none", "None"

    slot = models.OneToOneField(
        AppointmentSlot,
        on_delete=models.PROTECT,
        related_name="appointment",
        verbose_name="بازه",
    )
    patient = models.ForeignKey(
        PatientProfile,
        on_delete=models.PROTECT,
        related_name="appointments",
        verbose_name="مراجع",
    )
    therapist = models.ForeignKey(
        TherapistProfile,
        on_delete=models.PROTECT,
        related_name="appointments",
        verbose_name="درمانگر",
    )
    session_type = models.ForeignKey(
        SessionType,
        on_delete=models.PROTECT,
        related_name="appointments",
        verbose_name="نوع جلسه",
    )
    starts_at = models.DateTimeField(verbose_name="شروع")
    ends_at = models.DateTimeField(verbose_name="پایان")
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING_PAYMENT,
        db_index=True,
        verbose_name="وضعیت",
    )
    price_snapshot = models.DecimalField(
        max_digits=12, decimal_places=0, verbose_name="قیمت ثبت‌شده"
    )
    payment_ref = models.CharField(
        max_length=64, blank=True, verbose_name="مرجع پرداخت"
    )
    deposit_ledger_ref = models.CharField(
        max_length=64, blank=True, verbose_name="مرجع واریز دفترکل"
    )
    canceled_at = models.DateTimeField(
        null=True, blank=True, verbose_name="تاریخ لغو"
    )
    cancellation_reason = models.TextField(blank=True, verbose_name="دلیل لغو")
    refund_policy_applied = models.CharField(
        max_length=16,
        choices=RefundPolicy.choices,
        blank=True,
        verbose_name="سیاست بازپرداخت",
    )
    refund_ledger_ref = models.CharField(
        max_length=64, blank=True, verbose_name="مرجع بازپرداخت"
    )
    meeting_link = models.URLField(
        max_length=500, blank=True, verbose_name="لینک جلسه"
    )

    class Meta:
        ordering = ["-starts_at"]
        verbose_name = "نوبت"
        verbose_name_plural = "نوبت ها"

    def __str__(self) -> str:
        return f"Appointment<{self.pk}> {self.status}"


class TherapistReview(TimeStampedModel):
    """Patient rating of a completed appointment.

    Stars always count toward the therapist average. ``body`` is public
    only after an admin sets ``text_status`` to approved.
    """

    class TextStatus(models.TextChoices):
        NONE = "none", "No text"
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.CASCADE,
        related_name="review",
        verbose_name="نوبت",
    )
    patient = models.ForeignKey(
        PatientProfile,
        on_delete=models.PROTECT,
        related_name="therapist_reviews",
        verbose_name="مراجع",
    )
    therapist = models.ForeignKey(
        TherapistProfile,
        on_delete=models.PROTECT,
        related_name="reviews",
        verbose_name="درمانگر",
    )
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
        related_name="psy_review_moderations",
        verbose_name="بررسی‌کننده",
    )
    reviewed_at = models.DateTimeField(
        null=True, blank=True, verbose_name="تاریخ بررسی"
    )
    admin_note = models.TextField(blank=True, verbose_name="یادداشت مدیر")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "نظر مراجع"
        verbose_name_plural = "نظرات مراجعان"

    def __str__(self) -> str:
        return f"Review<{self.pk}> appt={self.appointment_id} {self.rating}★"


class SessionNote(TimeStampedModel):
    """Therapist note on an appointment. Hidden from the patient unless shared."""

    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.CASCADE,
        related_name="notes",
        verbose_name="نوبت",
    )
    author = models.ForeignKey(
        TherapistProfile,
        on_delete=models.PROTECT,
        related_name="session_notes",
        verbose_name="نویسنده",
    )
    body = models.TextField(verbose_name="متن")
    shared_with_patient = models.BooleanField(
        default=False, verbose_name="نمایش به مراجع"
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "یادداشت جلسه"
        verbose_name_plural = "یادداشت های جلسه"


# ===========================================================================
# Clinical records (private EHR — never visible to patients)
# ===========================================================================


class ClinicalReport(TimeStampedModel):
    """Mandatory private report after a completed appointment.

    Distinct from ``SessionNote``. Patients never see this record.
    """

    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.PROTECT,
        related_name="clinical_report",
        verbose_name="نوبت",
    )
    therapist = models.ForeignKey(
        TherapistProfile,
        on_delete=models.PROTECT,
        related_name="clinical_reports",
        verbose_name="درمانگر",
    )
    patient = models.ForeignKey(
        PatientProfile,
        on_delete=models.PROTECT,
        related_name="clinical_reports",
        verbose_name="مراجع",
    )
    summary = models.TextField(verbose_name="خلاصه جلسه")
    assessment = models.TextField(verbose_name="ارزیابی بالینی")
    treatment_plan = models.TextField(verbose_name="طرح درمان")
    risk_flags = models.JSONField(
        default=list, blank=True, verbose_name="پرچم‌های خطر"
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "گزارش بالینی"
        verbose_name_plural = "گزارش‌های بالینی"
        indexes = [
            models.Index(fields=["patient", "-created_at"]),
            models.Index(fields=["therapist", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"ClinicalReport<{self.pk}> appt={self.appointment_id}"


class FileAccessRequest(TimeStampedModel):
    """Therapist request for temporary access to a patient's master file."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"

    therapist = models.ForeignKey(
        TherapistProfile,
        on_delete=models.CASCADE,
        related_name="file_access_requests",
        verbose_name="درمانگر",
    )
    patient = models.ForeignKey(
        PatientProfile,
        on_delete=models.CASCADE,
        related_name="file_access_requests",
        verbose_name="مراجع",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        verbose_name="وضعیت",
    )
    reason = models.TextField(blank=True, verbose_name="دلیل")
    decision_note = models.TextField(blank=True, verbose_name="یادداشت تصمیم")
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_file_access_requests",
        verbose_name="تأییدکننده",
    )
    decided_at = models.DateTimeField(
        null=True, blank=True, verbose_name="تاریخ تصمیم"
    )
    expires_at = models.DateTimeField(
        null=True, blank=True, verbose_name="انقضا"
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "درخواست دسترسی پرونده"
        verbose_name_plural = "درخواست‌های دسترسی پرونده"
        indexes = [
            models.Index(fields=["patient", "status"]),
            models.Index(fields=["therapist", "status"]),
        ]

    def __str__(self) -> str:
        return (
            f"FileAccess<{self.pk}> t={self.therapist_id} "
            f"p={self.patient_id} ({self.status})"
        )


# ===========================================================================
# Psychometrics
# ===========================================================================


class PsychometricForm(TimeStampedModel):
    """Published questionnaire. ``schema`` is the question JSON; ``version`` is frozen on submit."""

    title = models.CharField(max_length=200, verbose_name="عنوان")
    slug = models.SlugField(unique=True, verbose_name="شناسه")
    description = models.TextField(blank=True, verbose_name="توضیحات")
    schema = models.JSONField(default=dict, verbose_name="ساختار")
    version = models.PositiveIntegerField(default=1, verbose_name="نسخه")
    is_published = models.BooleanField(default=False, verbose_name="منتشر شده")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="psychometric_forms_created",
        verbose_name="ایجادکننده",
    )

    class Meta:
        ordering = ["title"]
        verbose_name = "آزمون روان‌سنجی"
        verbose_name_plural = "آزمون های روان‌سنجی"

    def __str__(self) -> str:
        return f"{self.title} v{self.version}"


class PsychometricResponse(TimeStampedModel):
    """One patient's answers. Optionally routed to a therapist for review."""

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        REVIEWED = "reviewed", "Reviewed"

    form = models.ForeignKey(
        PsychometricForm,
        on_delete=models.PROTECT,
        related_name="responses",
        verbose_name="آزمون",
    )
    form_version = models.PositiveIntegerField(verbose_name="نسخه آزمون")
    patient = models.ForeignKey(
        PatientProfile,
        on_delete=models.CASCADE,
        related_name="psychometric_responses",
        verbose_name="مراجع",
    )
    answers = models.JSONField(default=dict, verbose_name="پاسخ‌ها")
    routed_therapist = models.ForeignKey(
        TherapistProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="routed_psychometric_responses",
        verbose_name="درمانگر ارجاع‌شده",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.SUBMITTED,
        verbose_name="وضعیت",
    )
    submitted_at = models.DateTimeField(
        auto_now_add=True, verbose_name="تاریخ ارسال"
    )
    reviewer_notes = models.TextField(blank=True, verbose_name="یادداشت بررسی")

    class Meta:
        ordering = ["-submitted_at"]
        verbose_name = "پاسخ آزمون"
        verbose_name_plural = "پاسخ های آزمون"


# ===========================================================================
# Workshops
# ===========================================================================


class Workshop(TimeStampedModel):
    """Public workshop catalog entry. Curriculum lives on sessions/resources."""

    title = models.CharField(max_length=200, verbose_name="عنوان")
    slug = models.SlugField(unique=True, verbose_name="شناسه")
    description = models.TextField(blank=True, verbose_name="توضیحات")
    body_md = models.TextField(
        blank=True,
        help_text="Long-form Markdown introduction for the detail page.",
        verbose_name="متن کامل",
    )
    instructor = models.ForeignKey(
        TherapistProfile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workshops",
        verbose_name="مدرس",
    )
    capacity = models.PositiveIntegerField(verbose_name="ظرفیت")
    price = models.DecimalField(
        max_digits=12, decimal_places=0, verbose_name="قیمت"
    )
    starts_at = models.DateTimeField(
        null=True, blank=True, verbose_name="شروع"
    )
    ends_at = models.DateTimeField(null=True, blank=True, verbose_name="پایان")
    banner_image = models.ImageField(
        upload_to="psy/workshops/",
        blank=True,
        max_length=500,
        verbose_name="تصویر بنر",
    )
    recording_url = models.URLField(blank=True, verbose_name="لینک ضبط")
    is_published = models.BooleanField(default=False, verbose_name="منتشر شده")
    certificate_enabled = models.BooleanField(
        default=False, verbose_name="صدور گواهی"
    )

    class Meta:
        ordering = ["-starts_at", "title"]
        verbose_name = "کارگاه"
        verbose_name_plural = "کارگاه ها"

    def __str__(self) -> str:
        return self.title


class WorkshopEnrollment(TimeStampedModel):
    """Patient seat on a workshop. One row per patient; status tracks pay/cancel."""

    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Pending payment"
        ACTIVE = "active", "Active"
        CANCELED = "canceled", "Canceled"
        REFUNDED = "refunded", "Refunded"

    workshop = models.ForeignKey(
        Workshop,
        on_delete=models.CASCADE,
        related_name="enrollments",
        verbose_name="کارگاه",
    )
    patient = models.ForeignKey(
        PatientProfile,
        on_delete=models.CASCADE,
        related_name="workshop_enrollments",
        verbose_name="مراجع",
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING_PAYMENT,
        verbose_name="وضعیت",
    )
    price_snapshot = models.DecimalField(
        max_digits=12, decimal_places=0, default=0, verbose_name="قیمت ثبت‌شده"
    )
    hold_expires_at = models.DateTimeField(
        null=True, blank=True, verbose_name="انقضای رزرو موقت"
    )
    payment_ref = models.CharField(
        max_length=64, blank=True, verbose_name="مرجع پرداخت"
    )
    deposit_ledger_ref = models.CharField(
        max_length=64, blank=True, verbose_name="مرجع واریز دفترکل"
    )
    refund_ledger_ref = models.CharField(
        max_length=64, blank=True, verbose_name="مرجع بازپرداخت"
    )
    canceled_at = models.DateTimeField(
        null=True, blank=True, verbose_name="تاریخ لغو"
    )
    cancellation_reason = models.TextField(blank=True, verbose_name="دلیل لغو")
    enrolled_at = models.DateTimeField(
        auto_now_add=True, verbose_name="تاریخ ثبت‌نام"
    )

    class Meta:
        unique_together = ("workshop", "patient")
        ordering = ["-enrolled_at"]
        verbose_name = "ثبت‌نام کارگاه"
        verbose_name_plural = "ثبت‌نام های کارگاه"


class WorkshopSession(TimeStampedModel):
    """One curriculum unit inside a workshop (live or recorded)."""

    workshop = models.ForeignKey(
        Workshop,
        on_delete=models.CASCADE,
        related_name="sessions",
        verbose_name="کارگاه",
    )
    sort_order = models.PositiveIntegerField(default=0, verbose_name="ترتیب")
    title = models.CharField(max_length=200, verbose_name="عنوان")
    summary = models.TextField(blank=True, verbose_name="خلاصه")
    starts_at = models.DateTimeField(
        null=True, blank=True, verbose_name="شروع"
    )
    ends_at = models.DateTimeField(null=True, blank=True, verbose_name="پایان")
    meeting_url = models.URLField(
        blank=True, max_length=500, verbose_name="لینک جلسه"
    )
    recording_url = models.URLField(
        blank=True, max_length=500, verbose_name="لینک ضبط"
    )

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "جلسه کارگاه"
        verbose_name_plural = "جلسات کارگاه"
        indexes = [
            models.Index(fields=["workshop", "sort_order"]),
        ]

    def __str__(self) -> str:
        return f"{self.workshop.slug}: {self.title}"


class WorkshopResource(TimeStampedModel):
    """Downloadable material. Optional ``session`` scopes it to one unit."""

    class Kind(models.TextChoices):
        PDF = "pdf", "PDF"
        SLIDES = "slides", "Slides"
        OTHER = "other", "Other"

    workshop = models.ForeignKey(
        Workshop,
        on_delete=models.CASCADE,
        related_name="resources",
        verbose_name="کارگاه",
    )
    session = models.ForeignKey(
        WorkshopSession,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="resources",
        verbose_name="جلسه",
    )
    sort_order = models.PositiveIntegerField(default=0, verbose_name="ترتیب")
    title = models.CharField(max_length=200, verbose_name="عنوان")
    kind = models.CharField(
        max_length=16,
        choices=Kind.choices,
        default=Kind.OTHER,
        verbose_name="نوع",
    )
    file_url = models.URLField(
        blank=True, max_length=500, verbose_name="لینک فایل"
    )

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "منبع کارگاه"
        verbose_name_plural = "منابع کارگاه"
        indexes = [
            models.Index(fields=["workshop", "sort_order"]),
        ]

    def __str__(self) -> str:
        return self.title


class WorkshopSessionProgress(TimeStampedModel):
    """Marks a session complete for one enrollment (used for certificates)."""

    enrollment = models.ForeignKey(
        WorkshopEnrollment,
        on_delete=models.CASCADE,
        related_name="session_progress",
        verbose_name="ثبت‌نام",
    )
    session = models.ForeignKey(
        WorkshopSession,
        on_delete=models.CASCADE,
        related_name="progress_rows",
        verbose_name="جلسه",
    )
    completed_at = models.DateTimeField(
        auto_now_add=True, verbose_name="تاریخ تکمیل"
    )

    class Meta:
        unique_together = ("enrollment", "session")
        ordering = ["-completed_at"]
        verbose_name = "پیشرفت جلسه"
        verbose_name_plural = "پیشرفت جلسات"


class WorkshopCertificate(TimeStampedModel):
    """Issued once per active enrollment when all sessions are complete."""

    enrollment = models.OneToOneField(
        WorkshopEnrollment,
        on_delete=models.CASCADE,
        related_name="certificate",
        verbose_name="ثبت‌نام",
    )
    issued_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ صدور")
    certificate_code = models.CharField(
        max_length=64, unique=True, verbose_name="کد گواهی"
    )
    file = models.FileField(
        upload_to="psy/certificates/",
        null=True,
        blank=True,
        verbose_name="فایل",
    )

    class Meta:
        verbose_name = "گواهی کارگاه"
        verbose_name_plural = "گواهی های کارگاه"


# ===========================================================================
# CMS
# ===========================================================================


class BlogPost(TimeStampedModel):
    """Public article. Drafts stay hidden until ``is_published`` is set."""

    title = models.CharField(max_length=200, verbose_name="عنوان")
    slug = models.SlugField(unique=True, verbose_name="شناسه")
    excerpt = models.TextField(blank=True, verbose_name="چکیده")
    body = models.TextField(verbose_name="متن")
    cover_image = models.ImageField(
        upload_to="psy/blog/",
        blank=True,
        max_length=500,
        verbose_name="تصویر جلد",
    )
    is_published = models.BooleanField(default=False, verbose_name="منتشر شده")
    published_at = models.DateTimeField(
        null=True, blank=True, verbose_name="تاریخ انتشار"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="psy_blog_posts",
        verbose_name="نویسنده",
    )

    class Meta:
        ordering = ["-published_at", "-created_at"]
        verbose_name = "مقاله"
        verbose_name_plural = "مقالات"


class NewsSlide(TimeStampedModel):
    """Landing carousel slide. Drafts stay hidden until ``is_published`` is set."""

    title = models.CharField(max_length=200, verbose_name="عنوان")
    body = models.TextField(blank=True, verbose_name="متن")
    image = models.ImageField(
        upload_to="psy/news/",
        blank=True,
        max_length=500,
        verbose_name="تصویر",
    )
    link_url = models.CharField(
        max_length=500,
        blank=True,
        verbose_name="لینک",
        help_text="Internal path or absolute URL.",
    )
    link_label = models.CharField(
        max_length=80, blank=True, verbose_name="متن دکمه"
    )
    sort_order = models.PositiveIntegerField(default=0, verbose_name="ترتیب")
    is_published = models.BooleanField(default=False, verbose_name="منتشر شده")

    class Meta:
        ordering = ["sort_order", "-created_at"]
        verbose_name = "اسلاید اخبار"
        verbose_name_plural = "اسلایدهای اخبار"
        indexes = [
            models.Index(fields=["is_published", "sort_order"]),
        ]

    def __str__(self) -> str:
        return self.title


class SitePage(TimeStampedModel):
    """Keyed CMS page (about, contact, …). ``body`` is structured JSON."""

    key = models.CharField(max_length=64, unique=True, verbose_name="کلید")
    title = models.CharField(max_length=200, verbose_name="عنوان")
    body = models.JSONField(default=dict, blank=True, verbose_name="متن")

    class Meta:
        verbose_name = "صفحه سایت"
        verbose_name_plural = "صفحات سایت"

    def __str__(self) -> str:
        return self.key


# ===========================================================================
# Support tickets
# ===========================================================================


class Ticket(TimeStampedModel):
    """Patient support thread. Withdrawal tickets store a finance ref, not a wallet write."""

    class Type(models.TextChoices):
        GENERAL = "general", "General"
        WITHDRAWAL = "withdrawal", "Withdrawal"
        COMPLAINT = "complaint", "Complaint"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    patient = models.ForeignKey(
        PatientProfile,
        on_delete=models.CASCADE,
        related_name="tickets",
        verbose_name="مراجع",
    )
    type = models.CharField(
        max_length=16,
        choices=Type.choices,
        default=Type.GENERAL,
        verbose_name="نوع",
    )
    subject = models.CharField(max_length=200, verbose_name="موضوع")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
        verbose_name="وضعیت",
    )
    withdrawal_ref = models.CharField(
        max_length=64, blank=True, verbose_name="مرجع برداشت"
    )
    bank_details_snapshot = models.JSONField(
        default=dict, blank=True, verbose_name="اطلاعات بانکی"
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "تیکت"
        verbose_name_plural = "تیکت ها"


class TicketMessage(TimeStampedModel):
    """One message on a ticket. ``is_staff_reply`` marks clinic-admin replies."""

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="تیکت",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="psy_ticket_messages",
        verbose_name="نویسنده",
    )
    body = models.TextField(verbose_name="متن")
    is_staff_reply = models.BooleanField(
        default=False, verbose_name="پاسخ کارکنان"
    )

    class Meta:
        ordering = ["created_at"]
        verbose_name = "پیام تیکت"
        verbose_name_plural = "پیام های تیکت"
