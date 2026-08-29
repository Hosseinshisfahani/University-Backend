"""
Psychology institute domain models.

Finance integration uses opaque reference strings and finance.services —
this app never mutates Wallet.balance directly.
"""

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.models import TimeStampedModel


class TherapistProfile(TimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="therapist_profile",
    )
    display_name = models.CharField(max_length=120)
    bio = models.TextField(blank=True)
    specialties = models.JSONField(default=list, blank=True)
    is_accepting_patients = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["display_name"]

    def __str__(self) -> str:
        return self.display_name


class PatientProfile(TimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="patient_profile",
    )
    national_id = models.CharField(max_length=20, blank=True, db_index=True)
    phone = models.CharField(max_length=32, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    notes_internal = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Patient<{self.user_id}>"


class SessionType(TimeStampedModel):
    class Modality(models.TextChoices):
        ONLINE = "online", "Online"
        IN_PERSON = "in_person", "In person"

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    modality = models.CharField(max_length=16, choices=Modality.choices)
    duration_minutes = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=12, decimal_places=0)
    buffer_minutes = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class TherapistSessionOffer(TimeStampedModel):
    therapist = models.ForeignKey(
        TherapistProfile,
        on_delete=models.CASCADE,
        related_name="session_offers",
    )
    session_type = models.ForeignKey(
        SessionType,
        on_delete=models.CASCADE,
        related_name="therapist_offers",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("therapist", "session_type")

    def __str__(self) -> str:
        return f"{self.therapist} → {self.session_type}"


class TherapistAvailability(TimeStampedModel):
    therapist = models.ForeignKey(
        TherapistProfile,
        on_delete=models.CASCADE,
        related_name="availabilities",
    )
    weekday = models.PositiveSmallIntegerField(
        help_text="0=Monday … 6=Sunday (Python weekday).",
    )
    start_time = models.TimeField()
    end_time = models.TimeField()
    timezone = models.CharField(max_length=64, default="Asia/Tehran")
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "therapist availabilities"
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
    therapist = models.ForeignKey(
        TherapistProfile,
        on_delete=models.CASCADE,
        related_name="availability_exceptions",
    )
    date = models.DateField()
    is_day_off = models.BooleanField(default=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = ("therapist", "date", "start_time", "end_time")

    def __str__(self) -> str:
        return f"Exception {self.therapist} {self.date}"


class LeaveRequest(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELED = "canceled", "Canceled"

    therapist = models.ForeignKey(
        TherapistProfile,
        on_delete=models.CASCADE,
        related_name="leave_requests",
    )
    starts_on = models.DateField()
    ends_on = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    reason = models.TextField()
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="psy_leave_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    admin_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_on__gte=F("starts_on")),
                name="psy_leave_end_on_or_after_start",
            ),
        ]

    def __str__(self) -> str:
        return f"Leave {self.therapist_id} {self.starts_on}–{self.ends_on} ({self.status})"


class AppointmentSlot(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        HELD = "held", "Held"
        BOOKED = "booked", "Booked"
        BLOCKED = "blocked", "Blocked"

    therapist = models.ForeignKey(
        TherapistProfile,
        on_delete=models.CASCADE,
        related_name="slots",
    )
    session_type = models.ForeignKey(
        SessionType,
        on_delete=models.PROTECT,
        related_name="slots",
        null=True,
        blank=True,
        help_text="Null while the slot is open inventory; set when held/booked.",
    )
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    generation_batch = models.UUIDField(null=True, blank=True)
    hold_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="psy_slot_end_after_start",
            ),
        ]

    def __str__(self) -> str:
        return f"Slot {self.therapist_id} {self.starts_at} ({self.status})"


class Appointment(TimeStampedModel):
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
    )
    patient = models.ForeignKey(
        PatientProfile,
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    therapist = models.ForeignKey(
        TherapistProfile,
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    session_type = models.ForeignKey(
        SessionType,
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING_PAYMENT,
        db_index=True,
    )
    price_snapshot = models.DecimalField(max_digits=12, decimal_places=0)
    payment_ref = models.CharField(max_length=64, blank=True)
    deposit_ledger_ref = models.CharField(max_length=64, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    refund_policy_applied = models.CharField(
        max_length=16,
        choices=RefundPolicy.choices,
        blank=True,
    )
    refund_ledger_ref = models.CharField(max_length=64, blank=True)
    meeting_link = models.URLField(max_length=500, blank=True)

    class Meta:
        ordering = ["-starts_at"]

    def __str__(self) -> str:
        return f"Appointment<{self.pk}> {self.status}"


class SessionNote(TimeStampedModel):
    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.CASCADE,
        related_name="notes",
    )
    author = models.ForeignKey(
        TherapistProfile,
        on_delete=models.PROTECT,
        related_name="session_notes",
    )
    body = models.TextField()
    shared_with_patient = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]


class PsychometricForm(TimeStampedModel):
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    schema = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=1)
    is_published = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="psychometric_forms_created",
    )

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:
        return f"{self.title} v{self.version}"


class PsychometricResponse(TimeStampedModel):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        REVIEWED = "reviewed", "Reviewed"

    form = models.ForeignKey(
        PsychometricForm,
        on_delete=models.PROTECT,
        related_name="responses",
    )
    form_version = models.PositiveIntegerField()
    patient = models.ForeignKey(
        PatientProfile,
        on_delete=models.CASCADE,
        related_name="psychometric_responses",
    )
    answers = models.JSONField(default=dict)
    routed_therapist = models.ForeignKey(
        TherapistProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="routed_psychometric_responses",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.SUBMITTED,
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewer_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-submitted_at"]


class Workshop(TimeStampedModel):
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    body_md = models.TextField(
        blank=True,
        help_text="Long-form Markdown introduction for the detail page.",
    )
    instructor = models.ForeignKey(
        TherapistProfile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workshops",
    )
    capacity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=12, decimal_places=0)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    banner_image = models.ImageField(
        upload_to="psy/workshops/",
        blank=True,
        max_length=500,
    )
    recording_url = models.URLField(blank=True)
    is_published = models.BooleanField(default=False)
    certificate_enabled = models.BooleanField(default=False)

    class Meta:
        ordering = ["-starts_at", "title"]

    def __str__(self) -> str:
        return self.title


class WorkshopEnrollment(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Pending payment"
        ACTIVE = "active", "Active"
        CANCELED = "canceled", "Canceled"
        REFUNDED = "refunded", "Refunded"

    workshop = models.ForeignKey(
        Workshop,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    patient = models.ForeignKey(
        PatientProfile,
        on_delete=models.CASCADE,
        related_name="workshop_enrollments",
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING_PAYMENT,
    )
    price_snapshot = models.DecimalField(
        max_digits=12, decimal_places=0, default=0
    )
    hold_expires_at = models.DateTimeField(null=True, blank=True)
    payment_ref = models.CharField(max_length=64, blank=True)
    deposit_ledger_ref = models.CharField(max_length=64, blank=True)
    refund_ledger_ref = models.CharField(max_length=64, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("workshop", "patient")
        ordering = ["-enrolled_at"]


class WorkshopSession(TimeStampedModel):
    workshop = models.ForeignKey(
        Workshop,
        on_delete=models.CASCADE,
        related_name="sessions",
    )
    sort_order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=200)
    summary = models.TextField(blank=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    meeting_url = models.URLField(blank=True, max_length=500)
    recording_url = models.URLField(blank=True, max_length=500)

    class Meta:
        ordering = ["sort_order", "id"]
        indexes = [
            models.Index(fields=["workshop", "sort_order"]),
        ]

    def __str__(self) -> str:
        return f"{self.workshop.slug}: {self.title}"


class WorkshopResource(TimeStampedModel):
    class Kind(models.TextChoices):
        PDF = "pdf", "PDF"
        SLIDES = "slides", "Slides"
        OTHER = "other", "Other"

    workshop = models.ForeignKey(
        Workshop,
        on_delete=models.CASCADE,
        related_name="resources",
    )
    session = models.ForeignKey(
        WorkshopSession,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="resources",
    )
    sort_order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=200)
    kind = models.CharField(
        max_length=16, choices=Kind.choices, default=Kind.OTHER
    )
    file_url = models.URLField(blank=True, max_length=500)

    class Meta:
        ordering = ["sort_order", "id"]
        indexes = [
            models.Index(fields=["workshop", "sort_order"]),
        ]

    def __str__(self) -> str:
        return self.title


class WorkshopSessionProgress(TimeStampedModel):
    enrollment = models.ForeignKey(
        WorkshopEnrollment,
        on_delete=models.CASCADE,
        related_name="session_progress",
    )
    session = models.ForeignKey(
        WorkshopSession,
        on_delete=models.CASCADE,
        related_name="progress_rows",
    )
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("enrollment", "session")
        ordering = ["-completed_at"]


class WorkshopCertificate(TimeStampedModel):
    enrollment = models.OneToOneField(
        WorkshopEnrollment,
        on_delete=models.CASCADE,
        related_name="certificate",
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    certificate_code = models.CharField(max_length=64, unique=True)
    file = models.FileField(upload_to="psy/certificates/", null=True, blank=True)


class BlogPost(TimeStampedModel):
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    excerpt = models.TextField(blank=True)
    body = models.TextField()
    cover_image = models.ImageField(
        upload_to="psy/blog/",
        blank=True,
        max_length=500,
    )
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="psy_blog_posts",
    )

    class Meta:
        ordering = ["-published_at", "-created_at"]


class SitePage(TimeStampedModel):
    key = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=200)
    body = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return self.key


class Ticket(TimeStampedModel):
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
    )
    type = models.CharField(max_length=16, choices=Type.choices, default=Type.GENERAL)
    subject = models.CharField(max_length=200)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    withdrawal_ref = models.CharField(max_length=64, blank=True)
    bank_details_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]


class TicketMessage(TimeStampedModel):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="psy_ticket_messages",
    )
    body = models.TextField()
    is_staff_reply = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at"]
