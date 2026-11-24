import uuid

from django.utils.text import slugify
from rest_framework import serializers

from apps.modules.forms.models import Form
from apps.modules.forms.models import Response as FormResponse
from apps.modules.booking.models import (
    Appointment,
    AppointmentSlot,
    AvailabilityException,
    LeaveRequest,
    SessionType,
    TherapistAvailability,
    TherapistSessionOffer,
)
from apps.modules.reviews.models import Review

from .models import (
    ClinicalReport,
    FileAccessRequest,
    PatientProfile,
    PsyReviewContext,
    SessionNote,
    TherapistProfile,
    Ticket,
    TicketMessage,
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


def _can_see_review_body(request, review) -> bool:
    from apps.modules.reviews.models import Review

    if review.text_status == Review.TextStatus.APPROVED:
        return True
    user = getattr(request, "user", None) if request else None
    if not user or not getattr(user, "is_authenticated", False):
        return False
    patient_id = review.psy_context.patient_id
    if hasattr(user, "patient_profile") and user.patient_profile.id == patient_id:
        return True
    from apps.kernel.tenancy.services import is_institute_admin

    if is_institute_admin(user, "psy"):
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
            "profile_image",
            "bio",
            "specialties",
            "is_accepting_patients",
            "is_active",
            "offers",
            "rating_avg",
            "rating_count",
        ]
        read_only_fields = ["profile_image"]

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
            offers = obj.provider.service_offers.filter(
                is_active=True, service_type__is_active=True
            ).select_related("service_type") if obj.provider_id else []
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
    session_type = SessionTypeSerializer(source="service_type", read_only=True)
    session_type_id = serializers.PrimaryKeyRelatedField(
        queryset=SessionType.objects.filter(is_active=True),
        source="service_type",
        write_only=True,
    )

    class Meta:
        model = TherapistSessionOffer
        fields = ["id", "session_type", "session_type_id", "is_active"]


class LeaveRequestSerializer(serializers.ModelSerializer):
    therapist = serializers.SerializerMethodField()
    therapist_name = serializers.SerializerMethodField()

    def get_therapist(self, obj):
        profile = getattr(obj.provider, "therapist_profile", None)
        return profile.id if profile else None

    def get_therapist_name(self, obj) -> str:
        return obj.provider.display_name

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
    session_type = SessionTypeSerializer(source="service_type", read_only=True)
    therapist = serializers.SerializerMethodField()

    def get_therapist(self, obj):
        profile = getattr(obj.provider, "therapist_profile", None)
        return TherapistProfileSerializer(profile).data if profile else None

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
    appointment = serializers.IntegerField(source="psy_context.appointment_id", read_only=True)
    patient = serializers.IntegerField(source="psy_context.patient_id", read_only=True)
    therapist = serializers.IntegerField(source="target_id", read_only=True)
    patient_first_name = serializers.SerializerMethodField()
    therapist_name = serializers.SerializerMethodField()
    body = serializers.SerializerMethodField()

    class Meta:
        model = Review
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

    def get_patient_first_name(self, obj: Review) -> str:
        return _patient_first_name(obj.psy_context.patient)

    def get_therapist_name(self, obj: Review) -> str:
        target = obj.target
        return getattr(target, "display_name", "") if target else ""

    def get_body(self, obj: Review) -> str:
        request = self.context.get("request")
        if _can_see_review_body(request, obj):
            return obj.body
        return ""


class PublicTherapistReviewSerializer(serializers.ModelSerializer):
    patient_first_name = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = [
            "id",
            "rating",
            "body",
            "patient_first_name",
            "created_at",
        ]

    def get_patient_first_name(self, obj: Review) -> str:
        return _patient_first_name(obj.psy_context.patient)


class AdminTherapistReviewSerializer(serializers.ModelSerializer):
    appointment = serializers.IntegerField(source="psy_context.appointment_id", read_only=True)
    patient = serializers.IntegerField(source="psy_context.patient_id", read_only=True)
    therapist = serializers.IntegerField(source="target_id", read_only=True)
    patient_first_name = serializers.SerializerMethodField()
    therapist_name = serializers.SerializerMethodField()

    class Meta:
        model = Review
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

    def get_patient_first_name(self, obj: Review) -> str:
        return _patient_first_name(obj.psy_context.patient)

    def get_therapist_name(self, obj: Review) -> str:
        target = obj.target
        return getattr(target, "display_name", "") if target else ""


class SubmitTherapistReviewSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    body = serializers.CharField(required=False, allow_blank=True, default="")


class AppointmentSerializer(serializers.ModelSerializer):
    patient = serializers.IntegerField(source="patient_id", read_only=True)
    therapist = serializers.IntegerField(source="therapist_id", read_only=True)
    session_type = serializers.IntegerField(source="service_type_id", read_only=True)
    therapist_name = serializers.CharField(
        source="provider.display_name", read_only=True
    )
    patient_name = serializers.SerializerMethodField()
    session_type_name = serializers.CharField(source="service_type.name", read_only=True)
    session_type_modality = serializers.CharField(
        source="service_type.modality", read_only=True
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
            review = obj.review_context.review
        except PsyReviewContext.DoesNotExist:
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


def _profile_display_name(patient: PatientProfile) -> str:
    user = patient.user
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.username


class ClinicalReportSerializer(serializers.ModelSerializer):
    appointment_starts_at = serializers.DateTimeField(
        source="appointment.starts_at", read_only=True
    )
    therapist_name = serializers.CharField(
        source="therapist.display_name", read_only=True
    )
    patient_name = serializers.SerializerMethodField()
    session_type_name = serializers.CharField(
        source="appointment.service_type.name", read_only=True
    )

    class Meta:
        model = ClinicalReport
        fields = [
            "id",
            "appointment",
            "appointment_starts_at",
            "session_type_name",
            "therapist",
            "therapist_name",
            "patient",
            "patient_name",
            "summary",
            "assessment",
            "treatment_plan",
            "risk_flags",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "appointment_starts_at",
            "session_type_name",
            "therapist",
            "therapist_name",
            "patient",
            "patient_name",
            "created_at",
            "updated_at",
        ]

    def get_patient_name(self, obj) -> str:
        return _profile_display_name(obj.patient)

    def get_extra_kwargs(self):
        kwargs = super().get_extra_kwargs()
        if self.instance is not None:
            kwargs["appointment"] = {"read_only": True}
        return kwargs


class FileAccessRequestSerializer(serializers.ModelSerializer):
    therapist_name = serializers.CharField(
        source="therapist.display_name", read_only=True
    )
    patient_name = serializers.SerializerMethodField()
    granted_by_name = serializers.SerializerMethodField()

    class Meta:
        model = FileAccessRequest
        fields = [
            "id",
            "therapist",
            "therapist_name",
            "patient",
            "patient_name",
            "status",
            "reason",
            "decision_note",
            "granted_by",
            "granted_by_name",
            "decided_at",
            "expires_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "therapist",
            "therapist_name",
            "patient_name",
            "status",
            "decision_note",
            "granted_by",
            "granted_by_name",
            "decided_at",
            "expires_at",
            "created_at",
            "updated_at",
        ]

    def get_patient_name(self, obj) -> str:
        return _profile_display_name(obj.patient)

    def get_granted_by_name(self, obj) -> str | None:
        user = obj.granted_by
        if not user:
            return None
        full = f"{user.first_name} {user.last_name}".strip()
        return full or user.username


class MissingReportAppointmentSerializer(serializers.ModelSerializer):
    patient = serializers.IntegerField(source="patient_id", read_only=True)
    therapist = serializers.IntegerField(source="therapist_id", read_only=True)
    patient_name = serializers.SerializerMethodField()
    therapist_name = serializers.CharField(
        source="provider.display_name", read_only=True
    )
    session_type_name = serializers.CharField(
        source="service_type.name", read_only=True
    )

    class Meta:
        model = Appointment
        fields = [
            "id",
            "patient",
            "patient_name",
            "therapist",
            "therapist_name",
            "session_type_name",
            "starts_at",
            "ends_at",
        ]

    def get_patient_name(self, obj) -> str:
        return _profile_display_name(obj.patient)


class ApproveFileAccessSerializer(serializers.Serializer):
    access_days = serializers.IntegerField(required=False, min_value=1, default=7)


class RejectFileAccessSerializer(serializers.Serializer):
    decision_note = serializers.CharField(
        required=False, allow_blank=True, default=""
    )


class PsychometricFormSerializer(serializers.ModelSerializer):
    class Meta:
        model = Form
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
    patient = serializers.SerializerMethodField()
    patient_name = serializers.SerializerMethodField()
    routed_therapist = serializers.SerializerMethodField()
    form_version = serializers.IntegerField(source="version.version", read_only=True)

    class Meta:
        model = FormResponse
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

    def get_patient(self, obj: FormResponse):
        profile = PatientProfile.objects.filter(user_id=obj.respondent_id).first()
        return profile.id if profile else None

    def get_routed_therapist(self, obj: FormResponse):
        if not obj.assigned_to_id:
            return None
        profile = TherapistProfile.objects.filter(user_id=obj.assigned_to_id).first()
        return profile.id if profile else None

    def get_patient_name(self, obj: FormResponse) -> str:
        user = obj.respondent
        full = f"{user.first_name} {user.last_name}".strip()
        return full or user.username


class SubmitPsychometricSerializer(serializers.Serializer):
    answers = serializers.JSONField()
    routed_therapist_id = serializers.IntegerField(required=False, allow_null=True)


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
    clinical_reports = ClinicalReportSerializer(many=True)
    has_full_file_access = serializers.BooleanField()
    pending_file_access_request = FileAccessRequestSerializer(allow_null=True)
    other_therapists_report_count = serializers.IntegerField()


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
