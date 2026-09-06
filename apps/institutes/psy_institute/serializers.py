import uuid

from django.utils.text import slugify
from rest_framework import serializers

from .models import (
    Appointment,
    AppointmentSlot,
    AvailabilityException,
    BlogPost,
    LeaveRequest,
    PatientProfile,
    PsychometricForm,
    PsychometricResponse,
    SessionNote,
    SessionType,
    SitePage,
    TherapistAvailability,
    TherapistProfile,
    TherapistReview,
    TherapistSessionOffer,
    Ticket,
    TicketMessage,
    Workshop,
    WorkshopCertificate,
    WorkshopEnrollment,
    WorkshopResource,
    WorkshopSession,
)


class SessionTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionType
        fields = [
            "id",
            "name",
            "slug",
            "modality",
            "duration_minutes",
            "price",
            "buffer_minutes",
            "is_active",
            "sort_order",
        ]
        extra_kwargs = {"slug": {"required": False, "allow_blank": True}}

    def create(self, validated_data):
        slug = (validated_data.get("slug") or "").strip()
        if not slug:
            validated_data["slug"] = self._unique_slug(validated_data["name"])
        return super().create(validated_data)

    def _unique_slug(self, name: str) -> str:
        base = slugify(name) or f"session-{uuid.uuid4().hex[:8]}"
        slug = base
        n = 2
        while SessionType.objects.filter(slug=slug).exists():
            slug = f"{base}-{n}"
            n += 1
        return slug


def _patient_first_name(patient: PatientProfile) -> str:
    name = (patient.user.first_name or "").strip()
    return name or "مراجع"


def _can_see_review_body(request, review: TherapistReview) -> bool:
    if review.text_status == TherapistReview.TextStatus.APPROVED:
        return True
    user = getattr(request, "user", None) if request else None
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if hasattr(user, "patient_profile") and user.patient_profile.id == review.patient_id:
        return True
    if user.is_staff or user.groups.filter(name="psy_admin").exists():
        return True
    return False


class TherapistProfileSerializer(serializers.ModelSerializer):
    offers = serializers.SerializerMethodField()
    rating_avg = serializers.SerializerMethodField()
    rating_count = serializers.SerializerMethodField()

    class Meta:
        model = TherapistProfile
        fields = [
            "id",
            "display_name",
            "bio",
            "specialties",
            "is_accepting_patients",
            "is_active",
            "offers",
            "rating_avg",
            "rating_count",
        ]

    def get_rating_avg(self, obj) -> float | None:
        avg = getattr(obj, "rating_avg", None)
        if avg is None:
            return None
        return round(float(avg), 2)

    def get_rating_count(self, obj) -> int:
        return int(getattr(obj, "rating_count", 0) or 0)

    def get_offers(self, obj) -> list:
        offers = getattr(obj, "active_offers", None)
        if offers is None:
            offers = obj.session_offers.filter(
                is_active=True, session_type__is_active=True
            ).select_related("session_type")
        return [
            {
                "id": offer.id,
                "is_active": offer.is_active,
                "session_type": SessionTypeSerializer(offer.session_type).data,
            }
            for offer in offers
        ]


class PatientProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientProfile
        fields = ["id", "national_id", "phone", "birth_date"]


class TherapistAvailabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = TherapistAvailability
        fields = [
            "id",
            "weekday",
            "start_time",
            "end_time",
            "timezone",
            "valid_from",
            "valid_until",
            "is_active",
        ]

    def validate(self, attrs):
        therapist = self.context.get("therapist") or getattr(
            self.instance, "therapist", None
        )
        weekday = attrs.get("weekday", getattr(self.instance, "weekday", None))
        if therapist is not None and weekday is not None:
            qs = TherapistAvailability.objects.filter(
                therapist=therapist, weekday=weekday
            )
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"weekday": "برای هر روز فقط یک بازه مجاز است."}
                )
        return attrs


class AvailabilityExceptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AvailabilityException
        fields = [
            "id",
            "date",
            "is_day_off",
            "start_time",
            "end_time",
            "reason",
        ]


class TherapistSessionOfferSerializer(serializers.ModelSerializer):
    session_type = SessionTypeSerializer(read_only=True)
    session_type_id = serializers.PrimaryKeyRelatedField(
        queryset=SessionType.objects.filter(is_active=True),
        source="session_type",
        write_only=True,
    )

    class Meta:
        model = TherapistSessionOffer
        fields = ["id", "session_type", "session_type_id", "is_active"]


class LeaveRequestSerializer(serializers.ModelSerializer):
    therapist_name = serializers.CharField(
        source="therapist.display_name", read_only=True
    )

    class Meta:
        model = LeaveRequest
        fields = [
            "id",
            "therapist",
            "therapist_name",
            "starts_on",
            "ends_on",
            "start_time",
            "end_time",
            "reason",
            "status",
            "admin_note",
            "reviewed_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "therapist",
            "therapist_name",
            "status",
            "admin_note",
            "reviewed_at",
            "created_at",
        ]


class SubmitLeaveRequestSerializer(serializers.Serializer):
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    reason = serializers.CharField()
    start_time = serializers.TimeField(required=False, allow_null=True)
    end_time = serializers.TimeField(required=False, allow_null=True)


class LeaveReviewSerializer(serializers.Serializer):
    admin_note = serializers.CharField(required=False, allow_blank=True, default="")


class AdminCreateSlotSerializer(serializers.Serializer):
    therapist_id = serializers.IntegerField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class AdminBookAppointmentSerializer(serializers.Serializer):
    patient_id = serializers.IntegerField()
    slot_id = serializers.IntegerField()
    session_type_id = serializers.IntegerField()
    payment = serializers.ChoiceField(
        choices=["pending", "wallet", "offline"], default="pending"
    )


class AppointmentSlotSerializer(serializers.ModelSerializer):
    session_type = SessionTypeSerializer(read_only=True)
    therapist = TherapistProfileSerializer(read_only=True)

    class Meta:
        model = AppointmentSlot
        fields = [
            "id",
            "therapist",
            "session_type",
            "starts_at",
            "ends_at",
            "status",
            "hold_expires_at",
        ]


class AdminAppointmentSlotSerializer(AppointmentSlotSerializer):
    appointment_id = serializers.SerializerMethodField()
    appointment_status = serializers.SerializerMethodField()
    patient_name = serializers.SerializerMethodField()

    class Meta(AppointmentSlotSerializer.Meta):
        fields = AppointmentSlotSerializer.Meta.fields + [
            "appointment_id",
            "appointment_status",
            "patient_name",
        ]

    def get_appointment_id(self, obj: AppointmentSlot):
        appt = self._appointment(obj)
        return appt.id if appt else None

    def get_appointment_status(self, obj: AppointmentSlot):
        appt = self._appointment(obj)
        return appt.status if appt else None

    def get_patient_name(self, obj: AppointmentSlot):
        appt = self._appointment(obj)
        if not appt:
            return None
        user = appt.patient.user
        full = f"{user.first_name} {user.last_name}".strip()
        return full or user.username

    def _appointment(self, obj: AppointmentSlot):
        try:
            return obj.appointment
        except Appointment.DoesNotExist:
            return None


class TherapistReviewSerializer(serializers.ModelSerializer):
    patient_first_name = serializers.SerializerMethodField()
    therapist_name = serializers.CharField(
        source="therapist.display_name", read_only=True
    )
    body = serializers.SerializerMethodField()

    class Meta:
        model = TherapistReview
        fields = [
            "id",
            "appointment",
            "patient",
            "patient_first_name",
            "therapist",
            "therapist_name",
            "rating",
            "body",
            "text_status",
            "admin_note",
            "created_at",
            "reviewed_at",
        ]
        read_only_fields = fields

    def get_patient_first_name(self, obj: TherapistReview) -> str:
        return _patient_first_name(obj.patient)

    def get_body(self, obj: TherapistReview) -> str:
        request = self.context.get("request")
        if _can_see_review_body(request, obj):
            return obj.body
        return ""


class PublicTherapistReviewSerializer(serializers.ModelSerializer):
    patient_first_name = serializers.SerializerMethodField()

    class Meta:
        model = TherapistReview
        fields = [
            "id",
            "rating",
            "body",
            "patient_first_name",
            "created_at",
        ]

    def get_patient_first_name(self, obj: TherapistReview) -> str:
        return _patient_first_name(obj.patient)


class AdminTherapistReviewSerializer(serializers.ModelSerializer):
    patient_first_name = serializers.SerializerMethodField()
    therapist_name = serializers.CharField(
        source="therapist.display_name", read_only=True
    )

    class Meta:
        model = TherapistReview
        fields = [
            "id",
            "appointment",
            "patient",
            "patient_first_name",
            "therapist",
            "therapist_name",
            "rating",
            "body",
            "text_status",
            "admin_note",
            "created_at",
            "reviewed_at",
        ]
        read_only_fields = fields

    def get_patient_first_name(self, obj: TherapistReview) -> str:
        return _patient_first_name(obj.patient)


class SubmitTherapistReviewSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    body = serializers.CharField(required=False, allow_blank=True, default="")


class AppointmentSerializer(serializers.ModelSerializer):
    therapist_name = serializers.CharField(
        source="therapist.display_name", read_only=True
    )
    patient_name = serializers.SerializerMethodField()
    session_type_name = serializers.CharField(source="session_type.name", read_only=True)
    session_type_modality = serializers.CharField(
        source="session_type.modality", read_only=True
    )
    review = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = [
            "id",
            "slot",
            "patient",
            "patient_name",
            "therapist",
            "therapist_name",
            "session_type",
            "session_type_name",
            "session_type_modality",
            "starts_at",
            "ends_at",
            "status",
            "price_snapshot",
            "payment_ref",
            "canceled_at",
            "cancellation_reason",
            "refund_policy_applied",
            "meeting_link",
            "created_at",
            "review",
        ]
        read_only_fields = fields

    def get_patient_name(self, obj: Appointment) -> str:
        user = obj.patient.user
        full = f"{user.first_name} {user.last_name}".strip()
        return full or user.username

    def get_review(self, obj: Appointment):
        try:
            review = obj.review
        except TherapistReview.DoesNotExist:
            return None
        if review is None:
            return None
        return TherapistReviewSerializer(review, context=self.context).data


class SetMeetingLinkSerializer(serializers.Serializer):
    meeting_link = serializers.URLField(
        max_length=500, required=False, allow_blank=True, default=""
    )


class BookAppointmentSerializer(serializers.Serializer):
    slot_id = serializers.IntegerField()
    session_type_id = serializers.IntegerField()


class ConfirmAppointmentSerializer(serializers.Serializer):
    payment_ref = serializers.CharField(max_length=64)
    idempotency_key = serializers.CharField(max_length=64)


class CancelAppointmentSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)


class MoveAppointmentSerializer(serializers.Serializer):
    new_slot_id = serializers.IntegerField()


class SessionNoteSerializer(serializers.ModelSerializer):
    appointment_starts_at = serializers.DateTimeField(
        source="appointment.starts_at", read_only=True
    )
    therapist_name = serializers.CharField(
        source="author.display_name", read_only=True
    )

    class Meta:
        model = SessionNote
        fields = [
            "id",
            "appointment",
            "appointment_starts_at",
            "therapist_name",
            "body",
            "shared_with_patient",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "appointment_starts_at",
            "therapist_name",
            "created_at",
            "updated_at",
        ]


class PsychometricFormSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychometricForm
        fields = [
            "id",
            "title",
            "slug",
            "description",
            "schema",
            "version",
            "is_published",
        ]


class PsychometricResponseSerializer(serializers.ModelSerializer):
    patient_name = serializers.SerializerMethodField()

    class Meta:
        model = PsychometricResponse
        fields = [
            "id",
            "form",
            "form_version",
            "patient",
            "patient_name",
            "answers",
            "routed_therapist",
            "status",
            "submitted_at",
            "reviewer_notes",
        ]
        read_only_fields = ["id", "form_version", "submitted_at", "status", "patient", "patient_name"]

    def get_patient_name(self, obj: PsychometricResponse) -> str:
        user = obj.patient.user
        full = f"{user.first_name} {user.last_name}".strip()
        return full or user.username


class SubmitPsychometricSerializer(serializers.Serializer):
    answers = serializers.JSONField()
    routed_therapist_id = serializers.IntegerField(required=False, allow_null=True)


class WorkshopSerializer(serializers.ModelSerializer):
    instructor_id = serializers.PrimaryKeyRelatedField(
        source="instructor",
        queryset=TherapistProfile.objects.all(),
        allow_null=True,
        required=False,
    )
    instructor_name = serializers.SerializerMethodField()
    seats_taken = serializers.SerializerMethodField()
    seats_remaining = serializers.SerializerMethodField()
    is_full = serializers.SerializerMethodField()

    class Meta:
        model = Workshop
        fields = [
            "id",
            "title",
            "slug",
            "description",
            "body_md",
            "instructor_id",
            "instructor_name",
            "capacity",
            "price",
            "starts_at",
            "ends_at",
            "banner_image",
            "recording_url",
            "is_published",
            "certificate_enabled",
            "seats_taken",
            "seats_remaining",
            "is_full",
        ]

    def get_instructor_name(self, obj: Workshop) -> str | None:
        return obj.instructor.display_name if obj.instructor_id else None

    def get_seats_taken(self, obj: Workshop) -> int:
        from .services.workshops import occupied_seats

        return occupied_seats(obj)

    def get_seats_remaining(self, obj: Workshop) -> int:
        from .services.workshops import seats_remaining

        return seats_remaining(obj)

    def get_is_full(self, obj: Workshop) -> bool:
        return self.get_seats_remaining(obj) <= 0

    def validate(self, attrs):
        is_published = attrs.get(
            "is_published", getattr(self.instance, "is_published", False)
        )
        if is_published:
            instructor = attrs.get(
                "instructor", getattr(self.instance, "instructor", None)
            )
            starts_at = attrs.get(
                "starts_at", getattr(self.instance, "starts_at", None)
            )
            capacity = attrs.get(
                "capacity", getattr(self.instance, "capacity", None)
            )
            if not instructor:
                raise serializers.ValidationError(
                    {"instructor_id": "Instructor required to publish."}
                )
            if not starts_at:
                raise serializers.ValidationError(
                    {"starts_at": "Start time required to publish."}
                )
            if not capacity or capacity < 1:
                raise serializers.ValidationError(
                    {"capacity": "Capacity must be at least 1."}
                )
        return attrs


class WorkshopResourcePublicSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    sort_order = serializers.IntegerField()
    title = serializers.CharField()
    kind = serializers.CharField()
    has_file = serializers.BooleanField()
    file_url = serializers.CharField(allow_null=True)
    is_locked = serializers.BooleanField()
    session_id = serializers.IntegerField(allow_null=True)


class WorkshopSessionPublicSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    sort_order = serializers.IntegerField()
    title = serializers.CharField()
    summary = serializers.CharField()
    starts_at = serializers.DateTimeField(allow_null=True)
    ends_at = serializers.DateTimeField(allow_null=True)
    has_meeting = serializers.BooleanField()
    has_recording = serializers.BooleanField()
    meeting_url = serializers.CharField(allow_null=True)
    recording_url = serializers.CharField(allow_null=True)
    is_locked = serializers.BooleanField()
    completed = serializers.BooleanField()
    resources = WorkshopResourcePublicSerializer(many=True)


class WorkshopCertificateSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkshopCertificate
        fields = ["id", "certificate_code", "issued_at", "file"]
        read_only_fields = fields


class WorkshopDetailSerializer(WorkshopSerializer):
    viewer_has_access = serializers.SerializerMethodField()
    progress_percent = serializers.SerializerMethodField()
    certificate = serializers.SerializerMethodField()
    sessions = serializers.SerializerMethodField()
    resources = serializers.SerializerMethodField()

    class Meta(WorkshopSerializer.Meta):
        fields = WorkshopSerializer.Meta.fields + [
            "viewer_has_access",
            "progress_percent",
            "certificate",
            "sessions",
            "resources",
        ]

    def _access(self, obj: Workshop) -> bool:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        from .services.workshops import viewer_has_content_access

        return viewer_has_content_access(user=user, workshop=obj)

    def _enrollment(self, obj: Workshop):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        from .services.workshops import get_active_enrollment

        return get_active_enrollment(user=user, workshop=obj)

    def get_viewer_has_access(self, obj: Workshop) -> bool:
        return self._access(obj)

    def get_progress_percent(self, obj: Workshop):
        from .services.workshops import progress_percent

        return progress_percent(enrollment=self._enrollment(obj), workshop=obj)

    def get_certificate(self, obj: Workshop):
        enrollment = self._enrollment(obj)
        if not enrollment:
            return None
        cert = WorkshopCertificate.objects.filter(enrollment=enrollment).first()
        if not cert:
            return None
        return WorkshopCertificateSerializer(cert).data

    def _serialize_resource(self, resource: WorkshopResource, *, access: bool) -> dict:
        has_file = bool(resource.file_url)
        return {
            "id": resource.id,
            "sort_order": resource.sort_order,
            "title": resource.title,
            "kind": resource.kind,
            "has_file": has_file,
            "file_url": resource.file_url if access and has_file else None,
            "is_locked": not access and has_file,
            "session_id": resource.session_id,
        }

    def get_sessions(self, obj: Workshop) -> list:
        access = self._access(obj)
        enrollment = self._enrollment(obj)
        completed_ids: set[int] = set()
        if enrollment:
            completed_ids = set(
                enrollment.session_progress.values_list("session_id", flat=True)
            )
        sessions = obj.sessions.prefetch_related("resources").all()
        out = []
        for session in sessions:
            has_meeting = bool(session.meeting_url)
            has_recording = bool(session.recording_url)
            resources = [
                self._serialize_resource(r, access=access)
                for r in session.resources.all()
            ]
            out.append(
                {
                    "id": session.id,
                    "sort_order": session.sort_order,
                    "title": session.title,
                    "summary": session.summary,
                    "starts_at": session.starts_at,
                    "ends_at": session.ends_at,
                    "has_meeting": has_meeting,
                    "has_recording": has_recording,
                    "meeting_url": session.meeting_url if access and has_meeting else None,
                    "recording_url": (
                        session.recording_url if access and has_recording else None
                    ),
                    "is_locked": not access and (has_meeting or has_recording),
                    "completed": session.id in completed_ids,
                    "resources": resources,
                }
            )
        return out

    def get_resources(self, obj: Workshop) -> list:
        """Workshop-level resources (not tied to a session)."""
        access = self._access(obj)
        rows = obj.resources.filter(session__isnull=True)
        return [self._serialize_resource(r, access=access) for r in rows]


class WorkshopSessionWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkshopSession
        fields = [
            "id",
            "sort_order",
            "title",
            "summary",
            "starts_at",
            "ends_at",
            "meeting_url",
            "recording_url",
        ]
        read_only_fields = ["id"]


class WorkshopResourceWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkshopResource
        fields = [
            "id",
            "session",
            "sort_order",
            "title",
            "kind",
            "file_url",
        ]
        read_only_fields = ["id"]


class WorkshopEnrollmentSerializer(serializers.ModelSerializer):
    workshop_title = serializers.CharField(source="workshop.title", read_only=True)
    workshop_slug = serializers.CharField(source="workshop.slug", read_only=True)
    workshop_starts_at = serializers.DateTimeField(
        source="workshop.starts_at", read_only=True, allow_null=True
    )
    workshop_ends_at = serializers.DateTimeField(
        source="workshop.ends_at", read_only=True, allow_null=True
    )
    workshop_banner_image = serializers.ImageField(
        source="workshop.banner_image", read_only=True
    )
    instructor_name = serializers.SerializerMethodField()
    patient_name = serializers.SerializerMethodField()
    patient_phone = serializers.CharField(source="patient.phone", read_only=True)

    class Meta:
        model = WorkshopEnrollment
        fields = [
            "id",
            "workshop",
            "workshop_title",
            "workshop_slug",
            "workshop_starts_at",
            "workshop_ends_at",
            "workshop_banner_image",
            "instructor_name",
            "patient",
            "patient_name",
            "patient_phone",
            "status",
            "price_snapshot",
            "hold_expires_at",
            "payment_ref",
            "deposit_ledger_ref",
            "refund_ledger_ref",
            "canceled_at",
            "cancellation_reason",
            "enrolled_at",
        ]
        read_only_fields = fields

    def get_instructor_name(self, obj: WorkshopEnrollment) -> str | None:
        inst = obj.workshop.instructor
        return inst.display_name if inst else None

    def get_patient_name(self, obj: WorkshopEnrollment) -> str:
        user = obj.patient.user
        full = f"{user.first_name} {user.last_name}".strip()
        return full or user.username


class ConfirmWorkshopEnrollmentSerializer(serializers.Serializer):
    payment_ref = serializers.CharField(max_length=64)
    idempotency_key = serializers.CharField(max_length=64)


class CancelWorkshopEnrollmentSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)


class BlogPostSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    author_therapist_id = serializers.SerializerMethodField()

    class Meta:
        model = BlogPost
        fields = [
            "id",
            "title",
            "slug",
            "excerpt",
            "body",
            "cover_image",
            "is_published",
            "published_at",
            "author_name",
            "author_therapist_id",
        ]
        read_only_fields = ["author_name", "author_therapist_id"]

    def get_author_name(self, obj: BlogPost) -> str | None:
        if not obj.author_id:
            return None
        user = obj.author
        full = (user.get_full_name() or "").strip()
        return full or user.username

    def get_author_therapist_id(self, obj: BlogPost) -> int | None:
        if not obj.author_id:
            return None
        profile = getattr(obj.author, "therapist_profile", None)
        return profile.id if profile else None


class SitePageSerializer(serializers.ModelSerializer):
    class Meta:
        model = SitePage
        fields = ["id", "key", "title", "body", "updated_at"]


class TicketMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketMessage
        fields = ["id", "author", "body", "is_staff_reply", "created_at"]
        read_only_fields = ["id", "author", "is_staff_reply", "created_at"]


class TicketSerializer(serializers.ModelSerializer):
    messages = TicketMessageSerializer(many=True, read_only=True)

    class Meta:
        model = Ticket
        fields = [
            "id",
            "type",
            "subject",
            "status",
            "withdrawal_ref",
            "bank_details_snapshot",
            "messages",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "withdrawal_ref",
            "created_at",
            "updated_at",
        ]


class CreateTicketSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=Ticket.Type.choices)
    subject = serializers.CharField(max_length=200)
    body = serializers.CharField()
    bank_details = serializers.JSONField(required=False)
    withdrawal_amount = serializers.DecimalField(
        max_digits=12, decimal_places=0, required=False, min_value=1
    )
    idempotency_key = serializers.CharField(max_length=64, required=False)


class RegenerateSlotsSerializer(serializers.Serializer):
    therapist_id = serializers.IntegerField()
    range_start = serializers.DateField()
    range_end = serializers.DateField()


class TherapistPatientSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    display_name = serializers.CharField()
    phone = serializers.CharField()
    appointments_count = serializers.IntegerField()
    last_appointment_at = serializers.DateTimeField(allow_null=True)
    last_appointment_status = serializers.CharField(allow_null=True)
    notes_count = serializers.IntegerField()


class TherapistPatientDetailSerializer(TherapistPatientSummarySerializer):
    recent_appointments = AppointmentSerializer(many=True)
    recent_notes = SessionNoteSerializer(many=True)
    recent_responses = PsychometricResponseSerializer(many=True)


class TherapistFinanceAppointmentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    starts_at = serializers.DateTimeField()
    session_type_name = serializers.CharField()
    patient_id = serializers.IntegerField()
    patient_name = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=0)
    status = serializers.CharField()


class TherapistFinanceReportSerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    total_income = serializers.DecimalField(max_digits=12, decimal_places=0)
    paid_sessions_count = serializers.IntegerField()
    upcoming_potential_revenue = serializers.DecimalField(
        max_digits=12, decimal_places=0
    )
    appointments = TherapistFinanceAppointmentSerializer(many=True)
