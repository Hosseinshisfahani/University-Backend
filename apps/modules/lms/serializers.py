from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.kernel.tenancy.services import (
    extend_payload,
    normalize_input,
    person_name,
    user_has_role,
)

from . import services
from .models import Certificate, Course, CourseResource, CourseSession, Enrollment

User = get_user_model()


class CourseSerializer(serializers.ModelSerializer):
    instructor_user_id = serializers.PrimaryKeyRelatedField(
        source="instructor",
        queryset=User.objects.all(),
        required=False,
        allow_null=True,
    )
    instructor_name = serializers.SerializerMethodField()
    seats_taken = serializers.SerializerMethodField()
    seats_remaining = serializers.SerializerMethodField()
    is_full = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = [
            "id",
            "title",
            "slug",
            "description",
            "body_md",
            "instructor_user_id",
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

    def get_instructor_name(self, obj: Course) -> str | None:
        if not obj.instructor_id:
            return None
        return person_name(obj.institute, obj.instructor)

    def get_seats_taken(self, obj: Course) -> int:
        return services.occupied_seats(obj)

    def get_seats_remaining(self, obj: Course) -> int:
        return services.seats_remaining(obj)

    def get_is_full(self, obj: Course) -> bool:
        return self.get_seats_remaining(obj) <= 0

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        institute = self.context.get("institute")
        if institute is not None and hasattr(data, "get"):
            legacy = data.get("instructor_id")
            has_user = data.get("instructor_user_id") not in (None, "")
            if legacy not in (None, "") and not has_user:
                translated = normalize_input(institute, "lms.course", {"instructor_id": legacy})
                if translated.get("_instructor_missing"):
                    raise serializers.ValidationError({"instructor_id": "Instructor not found."})
                if translated.get("instructor_user_id"):
                    data["instructor_user_id"] = translated["instructor_user_id"]
                try:
                    data.pop("instructor_id")
                except (KeyError, AttributeError):
                    pass
        return super().to_internal_value(data)

    def validate(self, attrs):
        instructor = attrs.get("instructor", getattr(self.instance, "instructor", None))
        institute = self.context.get("institute") or getattr(self.instance, "institute", None)
        if instructor is not None and institute is not None:
            slug = institute.slug
            if not (
                user_has_role(instructor, slug, "staff") or user_has_role(instructor, slug, "admin")
            ):
                raise serializers.ValidationError(
                    {"instructor_user_id": "Instructor must be staff of this institute."}
                )
        is_published = attrs.get("is_published", getattr(self.instance, "is_published", False))
        if is_published:
            starts_at = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
            capacity = attrs.get("capacity", getattr(self.instance, "capacity", None))
            if not instructor:
                raise serializers.ValidationError(
                    {"instructor_user_id": "Instructor required to publish."}
                )
            if not starts_at:
                raise serializers.ValidationError({"starts_at": "Start time required to publish."})
            if not capacity or capacity < 1:
                raise serializers.ValidationError({"capacity": "Capacity must be at least 1."})
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return extend_payload(instance.institute, "lms.course", instance, data)


class CourseResourcePublicSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    sort_order = serializers.IntegerField()
    title = serializers.CharField()
    kind = serializers.CharField()
    has_file = serializers.BooleanField()
    file_url = serializers.CharField(allow_null=True)
    is_locked = serializers.BooleanField()
    session_id = serializers.IntegerField(allow_null=True)


class CourseSessionPublicSerializer(serializers.Serializer):
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
    resources = CourseResourcePublicSerializer(many=True)


class CertificateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Certificate
        fields = ["id", "certificate_code", "issued_at", "file"]
        read_only_fields = fields


class CourseDetailSerializer(CourseSerializer):
    viewer_has_access = serializers.SerializerMethodField()
    progress_percent = serializers.SerializerMethodField()
    certificate = serializers.SerializerMethodField()
    sessions = serializers.SerializerMethodField()
    resources = serializers.SerializerMethodField()

    class Meta(CourseSerializer.Meta):
        fields = CourseSerializer.Meta.fields + [
            "viewer_has_access",
            "progress_percent",
            "certificate",
            "sessions",
            "resources",
        ]

    def _access(self, obj: Course) -> bool:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return services.viewer_has_content_access(user=user, course=obj)

    def _enrollment(self, obj: Course):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return services.get_active_enrollment(user=user, course=obj)

    def get_viewer_has_access(self, obj: Course) -> bool:
        return self._access(obj)

    def get_progress_percent(self, obj: Course):
        return services.progress_percent(enrollment=self._enrollment(obj), course=obj)

    def get_certificate(self, obj: Course):
        enrollment = self._enrollment(obj)
        if not enrollment:
            return None
        cert = Certificate.objects.filter(enrollment=enrollment).first()
        if not cert:
            return None
        return CertificateSerializer(cert).data

    def _serialize_resource(self, resource: CourseResource, *, access: bool) -> dict:
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

    def get_sessions(self, obj: Course) -> list:
        access = self._access(obj)
        enrollment = self._enrollment(obj)
        completed_ids: set[int] = set()
        if enrollment:
            completed_ids = set(enrollment.session_progress.values_list("session_id", flat=True))
        sessions = obj.sessions.prefetch_related("resources").all()
        out = []
        for session in sessions:
            has_meeting = bool(session.meeting_url)
            has_recording = bool(session.recording_url)
            resources = [self._serialize_resource(row, access=access) for row in session.resources.all()]
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
                    "recording_url": session.recording_url if access and has_recording else None,
                    "is_locked": not access and (has_meeting or has_recording),
                    "completed": session.id in completed_ids,
                    "resources": resources,
                }
            )
        return out

    def get_resources(self, obj: Course) -> list:
        access = self._access(obj)
        rows = obj.resources.filter(session__isnull=True)
        return [self._serialize_resource(row, access=access) for row in rows]


class CourseSessionWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseSession
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


class CourseResourceWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseResource
        fields = ["id", "session", "sort_order", "title", "kind", "file_url"]
        read_only_fields = ["id"]


class EnrollmentSerializer(serializers.ModelSerializer):
    course = serializers.IntegerField(source="workshop_id", read_only=True)
    course_title = serializers.CharField(source="workshop.title", read_only=True)
    course_slug = serializers.CharField(source="workshop.slug", read_only=True)
    course_starts_at = serializers.DateTimeField(source="workshop.starts_at", read_only=True, allow_null=True)
    course_ends_at = serializers.DateTimeField(source="workshop.ends_at", read_only=True, allow_null=True)
    course_banner_image = serializers.ImageField(source="workshop.banner_image", read_only=True)
    instructor_name = serializers.SerializerMethodField()
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = Enrollment
        fields = [
            "id",
            "course",
            "course_title",
            "course_slug",
            "course_starts_at",
            "course_ends_at",
            "course_banner_image",
            "instructor_name",
            "user_id",
            "user_name",
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

    def get_instructor_name(self, obj: Enrollment) -> str | None:
        instructor = obj.workshop.instructor
        if instructor is None:
            return None
        return person_name(obj.workshop.institute, instructor)

    def get_user_name(self, obj: Enrollment) -> str:
        return person_name(obj.workshop.institute, obj.user) or ""

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return extend_payload(instance.workshop.institute, "lms.enrollment", instance, data)


class ConfirmEnrollmentSerializer(serializers.Serializer):
    payment_ref = serializers.CharField(max_length=64)
    idempotency_key = serializers.CharField(max_length=64)


class CancelEnrollmentSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)
