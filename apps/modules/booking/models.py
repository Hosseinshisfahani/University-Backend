from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.db.models import F, Q

from apps.kernel.tenancy.models import InstituteScopedModel


def _rewrite_lookup(key: str) -> str:
    replacements = (
        ("patient__user", "customer"),
        ("therapist__user", "provider__user"),
        ("slot__therapist", "slot__provider__therapist_profile"),
        ("therapist_id", "provider__therapist_profile__id"),
        ("patient_id", "customer__patient_profile__id"),
        ("session_type_id", "service_type_id"),
        ("session_type", "service_type"),
        ("therapist", "provider__therapist_profile"),
        ("patient", "customer__patient_profile"),
    )
    for old, new in replacements:
        if key == old or key.startswith(old + "__"):
            return new + key[len(old) :]
    return key


def _rewrite_create(kwargs):
    data = dict(kwargs)
    if "patient" in data and "customer" not in data:
        data["customer"] = data.pop("patient").user
    if "therapist" in data and "provider" not in data:
        data["provider"] = data.pop("therapist").provider
    if "session_type" in data and "service_type" not in data:
        data["service_type"] = data.pop("session_type")
    if "institute" not in data and "institute_id" not in data:
        provider = data.get("provider")
        if provider is not None:
            data["institute_id"] = provider.institute_id
        else:
            raise ValueError("Booking rows need an institute or a provider.")
    return data


class CompatQuerySet(models.QuerySet):
    def filter(self, *args, **kwargs):
        return super().filter(*args, **{ _rewrite_lookup(k): v for k, v in kwargs.items() })

    def exclude(self, *args, **kwargs):
        return super().exclude(*args, **{ _rewrite_lookup(k): v for k, v in kwargs.items() })

    def select_related(self, *fields):
        if fields == (None,):
            return super().select_related(None)
        return super().select_related(*(_rewrite_lookup(field) for field in fields))

    def values(self, *fields, **expressions):
        return super().values(*(_rewrite_lookup(field) for field in fields), **expressions)

    def values_list(self, *fields, flat=False, named=False):
        return super().values_list(
            *(_rewrite_lookup(field) for field in fields),
            flat=flat,
            named=named,
        )


class CompatManager(models.Manager.from_queryset(CompatQuerySet)):
    def create(self, **kwargs):
        return super().create(**_rewrite_create(kwargs))

    def get_or_create(self, defaults=None, **kwargs):
        return super().get_or_create(defaults=defaults, **_rewrite_create(kwargs))

    def update_or_create(self, defaults=None, **kwargs):
        return super().update_or_create(defaults=defaults, **_rewrite_create(kwargs))


class BookingModel(InstituteScopedModel):
    objects = CompatManager()

    class Meta:
        abstract = True


class ServiceType(BookingModel):
    class Modality(models.TextChoices):
        ONLINE = "online", "Online"
        IN_PERSON = "in_person", "In person"

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=50)
    modality = models.CharField(max_length=16, choices=Modality.choices)
    duration_minutes = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=12, decimal_places=0)
    buffer_minutes = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["institute", "slug"], name="uniq_booking_service_slug"),
        ]


class Provider(BookingModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="booking_providers",
    )
    display_name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)
    is_accepting = models.BooleanField(default=True)
    shared_reviews = GenericRelation(
        "reviews.Review",
        content_type_field="target_type",
        object_id_field="target_id",
        related_query_name="provider_review",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["institute", "user"], name="uniq_booking_provider_user"),
        ]


class ProviderServiceOffer(BookingModel):
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="service_offers")
    service_type = models.ForeignKey(ServiceType, on_delete=models.CASCADE, related_name="provider_offers")
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "service_type"],
                name="uniq_booking_provider_service",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.provider_id and not self.institute_id:
            self.institute_id = self.provider.institute_id
        super().save(*args, **kwargs)

    @property
    def session_type(self):
        return self.service_type

    @property
    def therapist(self):
        return getattr(self.provider, "therapist_profile", None)


class ProviderAvailability(BookingModel):
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="availabilities")
    weekday = models.PositiveSmallIntegerField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    timezone = models.CharField(max_length=64, default="Asia/Tehran")
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(end_time__gt=F("start_time")),
                name="booking_availability_end_after_start",
            ),
            models.UniqueConstraint(
                fields=["provider", "weekday"],
                name="booking_availability_unique_weekday",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.provider_id and not self.institute_id:
            self.institute_id = self.provider.institute_id
        super().save(*args, **kwargs)

    @property
    def therapist(self):
        return getattr(self.provider, "therapist_profile", None)


class AvailabilityException(BookingModel):
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="availability_exceptions")
    date = models.DateField()
    is_day_off = models.BooleanField(default=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "date", "start_time", "end_time"],
                name="uniq_booking_availability_exception",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.provider_id and not self.institute_id:
            self.institute_id = self.provider.institute_id
        super().save(*args, **kwargs)

    @property
    def therapist(self):
        return getattr(self.provider, "therapist_profile", None)


class LeaveRequest(BookingModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELED = "canceled", "Canceled"

    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="leave_requests")
    starts_on = models.DateField()
    ends_on = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="booking_leave_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    admin_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_on__gte=F("starts_on")),
            name="booking_leave_end_on_or_after_start",
        ),
    ]

    @property
    def therapist(self):
        return getattr(self.provider, "therapist_profile", None)

    def save(self, *args, **kwargs):
        if self.provider_id and not self.institute_id:
            self.institute_id = self.provider.institute_id
        super().save(*args, **kwargs)


class Slot(BookingModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        HELD = "held", "Held"
        BOOKED = "booked", "Booked"
        BLOCKED = "blocked", "Blocked"

    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="slots")
    service_type = models.ForeignKey(
        ServiceType,
        on_delete=models.PROTECT,
        related_name="slots",
        null=True,
        blank=True,
    )
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True)
    generation_batch = models.UUIDField(null=True, blank=True)
    hold_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="booking_slot_end_after_start",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.provider_id and not self.institute_id:
            self.institute_id = self.provider.institute_id
        super().save(*args, **kwargs)

    @property
    def therapist(self):
        return getattr(self.provider, "therapist_profile", None)

    @property
    def therapist_id(self):
        profile = self.therapist
        return profile.id if profile else None

    @property
    def session_type(self):
        return self.service_type

    @property
    def session_type_id(self):
        return self.service_type_id


class Appointment(BookingModel):
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

    slot = models.OneToOneField(Slot, on_delete=models.PROTECT, related_name="appointment")
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="booking_appointments",
    )
    provider = models.ForeignKey(Provider, on_delete=models.PROTECT, related_name="appointments")
    service_type = models.ForeignKey(ServiceType, on_delete=models.PROTECT, related_name="appointments")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING_PAYMENT, db_index=True)
    price_snapshot = models.DecimalField(max_digits=12, decimal_places=0)
    payment_ref = models.CharField(max_length=64, blank=True)
    deposit_ledger_ref = models.CharField(max_length=64, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    refund_policy_applied = models.CharField(max_length=16, choices=RefundPolicy.choices, blank=True)
    refund_ledger_ref = models.CharField(max_length=64, blank=True)
    meeting_link = models.URLField(max_length=500, blank=True)

    class Meta:
        ordering = ["-starts_at"]

    def save(self, *args, **kwargs):
        if self.provider_id and not self.institute_id:
            self.institute_id = self.provider.institute_id
        super().save(*args, **kwargs)

    @property
    def patient(self):
        return getattr(self.customer, "patient_profile", None)

    @property
    def patient_id(self):
        profile = self.patient
        return profile.id if profile else None

    @property
    def therapist(self):
        return getattr(self.provider, "therapist_profile", None)

    @property
    def therapist_id(self):
        profile = self.therapist
        return profile.id if profile else None

    @property
    def session_type(self):
        return self.service_type

    @property
    def session_type_id(self):
        return self.service_type_id


class AppointmentReview(BookingModel):
    """One completed appointment can have one review. The review targets the provider."""

    review = models.OneToOneField(
        "reviews.Review",
        on_delete=models.CASCADE,
        related_name="appointment_link",
    )
    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.CASCADE,
        related_name="review_link",
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="appointment_reviews",
    )

    def save(self, *args, **kwargs):
        if self.appointment_id and not self.institute_id:
            self.institute_id = self.appointment.institute_id
        super().save(*args, **kwargs)


SessionType = ServiceType
AppointmentSlot = Slot
TherapistSessionOffer = ProviderServiceOffer
TherapistAvailability = ProviderAvailability
