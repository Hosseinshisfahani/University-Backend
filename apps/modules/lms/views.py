"""Course catalog, enrollment, and curriculum management."""

from __future__ import annotations

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.kernel.tenancy.permissions import (
    HasMemberRole,
    IsInstituteAdmin,
    IsInstituteAdminOrReadOnly,
    IsInstituteStaff,
)
from apps.kernel.tenancy.scoping import InstituteScopedMixin
from apps.kernel.tenancy.services import is_institute_admin, user_has_role

from . import services
from .models import Certificate, Course, CourseResource, CourseSession, Enrollment
from .serializers import (
    CancelEnrollmentSerializer,
    CertificateSerializer,
    ConfirmEnrollmentSerializer,
    CourseDetailSerializer,
    CourseResourceWriteSerializer,
    CourseSerializer,
    CourseSessionWriteSerializer,
    EnrollmentSerializer,
)


def _course_error(exc: services.CourseError) -> Response:
    status_code = 403 if exc.code == "forbidden" else 400
    return Response({"code": exc.code, "detail": str(exc), **exc.extra}, status=status_code)


class CourseViewSet(InstituteScopedMixin, viewsets.ModelViewSet):
    required_module = "lms"
    queryset = Course.objects.select_related("instructor", "institute")
    serializer_class = CourseSerializer
    lookup_field = "slug"
    permission_classes = [IsInstituteAdminOrReadOnly]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return CourseDetailSerializer
        return CourseSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["institute"] = getattr(self, "institute", None)
        return context

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        is_admin = is_institute_admin(user, self.institute.slug)
        if is_admin:
            pass
        elif self.action in ("list", "enroll"):
            qs = qs.filter(is_published=True)
        elif self.action in (
            "retrieve",
            "complete_session",
            "issue_certificate",
            "get_certificate",
            "roster",
            "confirm_enrollment",
            "cancel_enrollment",
        ):
            if user_has_role(user, self.institute.slug, "staff"):
                qs = qs.filter(Q(is_published=True) | Q(instructor=user))
            else:
                qs = qs.filter(is_published=True)
        if self.action == "list" and self.request.query_params.get("upcoming") == "1":
            qs = qs.filter(starts_at__gte=timezone.now())
        if self.action == "retrieve":
            qs = qs.prefetch_related("sessions__resources", "resources")
        return qs

    def _require_active_enrollment(self, request, course):
        enrollment = services.get_active_enrollment(user=request.user, course=course)
        if enrollment:
            return enrollment, None
        return None, Response(
            {"code": "forbidden", "detail": "Active enrollment required."},
            status=403,
        )

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, HasMemberRole])
    def enroll(self, request, slug=None, **kwargs):
        course = self.get_object()
        try:
            enrollment = services.enroll(course=course, user=request.user)
        except services.CourseError as exc:
            return _course_error(exc)
        return Response(EnrollmentSerializer(enrollment).data, status=201)

    @action(
        detail=True,
        methods=["post"],
        url_path=r"enrollments/(?P<enrollment_id>[^/.]+)/confirm",
        permission_classes=[IsAuthenticated, HasMemberRole],
    )
    def confirm_enrollment(self, request, slug=None, enrollment_id=None, **kwargs):
        course = self.get_object()
        enrollment = get_object_or_404(
            Enrollment,
            pk=enrollment_id,
            workshop=course,
            user=request.user,
        )
        ser = ConfirmEnrollmentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            enrollment = services.confirm_enrollment(
                enrollment=enrollment,
                payment_ref=ser.validated_data["payment_ref"],
                idempotency_key=ser.validated_data["idempotency_key"],
            )
        except services.CourseError as exc:
            return _course_error(exc)
        return Response(EnrollmentSerializer(enrollment).data)

    @action(
        detail=True,
        methods=["post"],
        url_path=r"enrollments/(?P<enrollment_id>[^/.]+)/cancel",
        permission_classes=[IsAuthenticated],
    )
    def cancel_enrollment(self, request, slug=None, enrollment_id=None, **kwargs):
        course = self.get_object()
        enrollment = get_object_or_404(
            Enrollment.objects.select_related("user", "workshop"),
            pk=enrollment_id,
            workshop=course,
            institute=self.institute,
        )
        is_admin = is_institute_admin(request.user, self.institute.slug)
        is_owner = (
            enrollment.user_id == request.user.id
            and user_has_role(request.user, self.institute.slug, "member")
        )
        if not (is_admin or is_owner):
            return Response({"detail": "Forbidden."}, status=403)
        ser = CancelEnrollmentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            enrollment = services.cancel_enrollment(
                enrollment=enrollment,
                canceled_by="admin" if is_admin else "patient",
                reason=ser.validated_data.get("reason", ""),
            )
        except services.CourseError as exc:
            return _course_error(exc)
        return Response(EnrollmentSerializer(enrollment).data)

    @action(detail=True, methods=["get"], url_path="roster", permission_classes=[IsAuthenticated])
    def roster(self, request, slug=None, **kwargs):
        course = self.get_object()
        is_admin = is_institute_admin(request.user, self.institute.slug)
        is_instructor = course.instructor_id == request.user.id and user_has_role(
            request.user, self.institute.slug, "staff"
        )
        if not (is_admin or is_instructor):
            return Response({"detail": "Forbidden."}, status=403)
        rows = (
            Enrollment.objects.filter(
                workshop=course,
                institute=self.institute,
                status=Enrollment.Status.ACTIVE,
            )
            .select_related("user", "workshop__instructor", "workshop__institute")
            .order_by("enrolled_at")
        )
        return Response(EnrollmentSerializer(rows, many=True).data)

    @action(
        detail=True,
        methods=["post"],
        url_path=r"sessions/(?P<session_id>[^/.]+)/complete",
        permission_classes=[IsAuthenticated, HasMemberRole],
    )
    def complete_session(self, request, slug=None, session_id=None, **kwargs):
        course = self.get_object()
        enrollment, error = self._require_active_enrollment(request, course)
        if error:
            return error
        session = get_object_or_404(CourseSession, pk=session_id, workshop=course)
        try:
            services.mark_session_complete(enrollment=enrollment, session=session)
        except services.CourseError as exc:
            return _course_error(exc)
        return Response(CourseDetailSerializer(course, context={"request": request, "institute": self.institute}).data)

    @action(
        detail=True,
        methods=["post"],
        url_path="certificate/issue",
        permission_classes=[IsAuthenticated, HasMemberRole],
    )
    def issue_certificate(self, request, slug=None, **kwargs):
        course = self.get_object()
        enrollment, error = self._require_active_enrollment(request, course)
        if error:
            return error
        try:
            cert = services.issue_certificate(enrollment=enrollment)
        except services.CourseError as exc:
            return _course_error(exc)
        return Response(CertificateSerializer(cert).data, status=201)

    @action(
        detail=True,
        methods=["get"],
        url_path="certificate",
        permission_classes=[IsAuthenticated, HasMemberRole],
    )
    def get_certificate(self, request, slug=None, **kwargs):
        course = self.get_object()
        enrollment, error = self._require_active_enrollment(request, course)
        if error:
            return error
        cert = Certificate.objects.filter(enrollment=enrollment).first()
        if not cert:
            return Response({"detail": "Certificate not issued yet."}, status=404)
        return Response(CertificateSerializer(cert).data)


class CourseSessionListCreateView(InstituteScopedMixin, APIView):
    required_module = "lms"
    permission_classes = [IsAuthenticated, IsInstituteAdmin]

    def get(self, request, course_slug, **kwargs):
        course = get_object_or_404(Course, slug=course_slug, institute=self.institute)
        return Response(CourseSessionWriteSerializer(course.sessions.all(), many=True).data)

    def post(self, request, course_slug, **kwargs):
        course = get_object_or_404(Course, slug=course_slug, institute=self.institute)
        ser = CourseSessionWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        session = CourseSession.objects.create(workshop=course, institute=course.institute, **ser.validated_data)
        return Response(CourseSessionWriteSerializer(session).data, status=201)


class CourseSessionDetailView(InstituteScopedMixin, APIView):
    required_module = "lms"
    permission_classes = [IsAuthenticated, IsInstituteAdmin]

    def patch(self, request, course_slug, pk, **kwargs):
        session = get_object_or_404(
            CourseSession,
            pk=pk,
            workshop__slug=course_slug,
            workshop__institute=self.institute,
        )
        ser = CourseSessionWriteSerializer(session, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)

    def delete(self, request, course_slug, pk, **kwargs):
        session = get_object_or_404(
            CourseSession,
            pk=pk,
            workshop__slug=course_slug,
            workshop__institute=self.institute,
        )
        session.delete()
        return Response(status=204)


class CourseResourceListCreateView(InstituteScopedMixin, APIView):
    required_module = "lms"
    permission_classes = [IsAuthenticated, IsInstituteAdmin]

    def get(self, request, course_slug, **kwargs):
        course = get_object_or_404(Course, slug=course_slug, institute=self.institute)
        rows = course.resources.select_related("session").all()
        return Response(CourseResourceWriteSerializer(rows, many=True).data)

    def post(self, request, course_slug, **kwargs):
        course = get_object_or_404(Course, slug=course_slug, institute=self.institute)
        ser = CourseResourceWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        session = ser.validated_data.get("session")
        if session and session.workshop_id != course.id:
            return Response({"detail": "Session must belong to this workshop."}, status=400)
        resource = CourseResource.objects.create(
            workshop=course,
            institute=course.institute,
            **ser.validated_data,
        )
        return Response(CourseResourceWriteSerializer(resource).data, status=201)


class CourseResourceDetailView(InstituteScopedMixin, APIView):
    required_module = "lms"
    permission_classes = [IsAuthenticated, IsInstituteAdmin]

    def patch(self, request, course_slug, pk, **kwargs):
        resource = get_object_or_404(
            CourseResource,
            pk=pk,
            workshop__slug=course_slug,
            workshop__institute=self.institute,
        )
        ser = CourseResourceWriteSerializer(resource, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        session = ser.validated_data.get("session", resource.session)
        if session and session.workshop_id != resource.workshop_id:
            return Response({"detail": "Session must belong to this workshop."}, status=400)
        ser.save()
        return Response(ser.data)

    def delete(self, request, course_slug, pk, **kwargs):
        resource = get_object_or_404(
            CourseResource,
            pk=pk,
            workshop__slug=course_slug,
            workshop__institute=self.institute,
        )
        resource.delete()
        return Response(status=204)


class MyEnrollmentListView(InstituteScopedMixin, APIView):
    required_module = "lms"
    permission_classes = [IsAuthenticated, HasMemberRole]

    def get(self, request, **kwargs):
        rows = (
            Enrollment.objects.filter(user=request.user, institute=self.institute)
            .exclude(status=Enrollment.Status.CANCELED)
            .select_related("workshop__instructor", "workshop__institute", "user")
            .order_by("-enrolled_at")
        )
        return Response(EnrollmentSerializer(rows, many=True).data)


class TeachingCourseListView(InstituteScopedMixin, APIView):
    required_module = "lms"
    permission_classes = [IsAuthenticated, IsInstituteStaff]

    def get(self, request, **kwargs):
        qs = (
            Course.objects.filter(instructor=request.user, institute=self.institute)
            .select_related("instructor", "institute")
            .order_by("-starts_at")
        )
        return Response(
            CourseSerializer(qs, many=True, context={"request": request, "institute": self.institute}).data
        )
