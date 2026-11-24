"""Psychology Institute portal REST views.

Serves the public catalog, patient portal, and therapist portal.

Clinic-admin aggregates live in ``admin_api.py``.
Therapist schedule CRUD lives in ``schedule_admin.py``.
Business rules live in ``services/`` — views only authenticate, scope
querysets, and translate service errors into HTTP responses.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Avg, Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.kernel.finance import services as finance_services
from apps.modules.forms.models import Form as PsychometricForm
from apps.modules.forms.models import Response as PsychometricResponse
from apps.modules.forms.services import submit_response as submit_form_response

from . import services
from apps.modules.booking.models import (
    Appointment,
    AppointmentSlot,
    AvailabilityException,
    LeaveRequest,
    SessionType,
    TherapistAvailability,
    TherapistSessionOffer,
)
from .models import (
    ClinicalReport,
    FileAccessRequest,
    PatientProfile,
    SessionNote,
    TherapistProfile,
    Ticket,
    TicketMessage,
)
from .permissions import IsPatient, IsPsyAdmin, IsPsyAdminOrReadOnly, IsTherapist
from .serializers import (
    AppointmentSerializer,
    AppointmentSlotSerializer,
    AvailabilityExceptionSerializer,
    BookAppointmentSerializer,
    CancelAppointmentSerializer,
    ClinicalReportSerializer,
    ConfirmAppointmentSerializer,
    CreateTicketSerializer,
    FileAccessRequestSerializer,
    LeaveRequestSerializer,
    MissingReportAppointmentSerializer,
    MoveAppointmentSerializer,
    ApproveFileAccessSerializer,
    RejectFileAccessSerializer,
    PsychometricFormSerializer,
    PsychometricResponseSerializer,
    PublicTherapistReviewSerializer,
    RegenerateSlotsSerializer,
    SessionNoteSerializer,
    SessionTypeSerializer,
    SetMeetingLinkSerializer,
    SubmitLeaveRequestSerializer,
    SubmitPsychometricSerializer,
    SubmitTherapistReviewSerializer,
    TherapistAvailabilitySerializer,
    TherapistFinanceReportSerializer,
    TherapistPatientSummarySerializer,
    TherapistProfileSerializer,
    TherapistReviewSerializer,
    TherapistSessionOfferSerializer,
    TicketMessageSerializer,
    TicketSerializer,
)

PSY_ADMIN_GROUP = "psy_admin"
PSY_ROLE_GROUPS = ("psy_admin", "psy_therapist", "psy_patient")
SCHEDULE_ADMIN_MANAGED_MSG = "Therapist schedule is managed by clinic admin."


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------



def request_institute(request, module_id="booking"):
    """Legacy ``/psy/`` routes stay on psy. Scoped routes use the URL slug."""
    from django.http import Http404

    from apps.kernel.tenancy.hosts import require_host_agreement
    from apps.kernel.tenancy.models import Institute

    match = getattr(request, "resolver_match", None)
    slug = (match.kwargs.get("institute_slug") if match else None) or "psy"
    institute = Institute.objects.filter(slug=slug, is_active=True).first()
    if institute is None or not institute.module_enabled(module_id):
        raise Http404("ماژول پیدا نشد.")
    require_host_agreement(request, institute)
    return institute


def _is_clinic_admin(user) -> bool:
    """Active psy admin membership. ``is_staff`` is not a clinic bypass."""
    from apps.kernel.tenancy.services import is_institute_admin

    return is_institute_admin(user, "psy")


def _patient_profile(user):
    if user and hasattr(user, "patient_profile"):
        return user.patient_profile
    return None


def _therapist_profile(user):
    if user and hasattr(user, "therapist_profile"):
        return user.therapist_profile
    return None


def _detail(message: str, status_code: int = 400) -> Response:
    return Response({"detail": message}, status=status_code)


def _forbidden(message: str = "Forbidden.") -> Response:
    return _detail(message, 403)


def _appointment_payload(appt, request, *, many=False):
    return AppointmentSerializer(appt, many=many, context={"request": request}).data


def _patient_display_name(patient: PatientProfile) -> str:
    user = patient.user
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.username


def _therapist_patient_ids(therapist: TherapistProfile):
    return (
        Appointment.objects.filter(therapist=therapist)
        .values_list("patient_id", flat=True)
        .distinct()
    )


def _build_patient_summary(therapist: TherapistProfile, patient: PatientProfile) -> dict:
    appts = Appointment.objects.filter(therapist=therapist, patient=patient).order_by(
        "-starts_at"
    )
    last = appts.first()
    notes_count = SessionNote.objects.filter(
        author=therapist, appointment__customer__patient_profile=patient
    ).count()
    return {
        "id": patient.id,
        "display_name": _patient_display_name(patient),
        "phone": patient.phone,
        "appointments_count": appts.count(),
        "last_appointment_at": last.starts_at if last else None,
        "last_appointment_status": last.status if last else None,
        "notes_count": notes_count,
    }


class AdminManagedScheduleMixin:
    """Therapist self-service schedule endpoints are intentionally disabled.

    Availability, exceptions, and session offers are owned by clinic admin
    (see ``schedule_admin.py``). These viewsets stay registered so old
    client URLs return a clear 403 instead of 404.
    """

    permission_classes = [IsAuthenticated, IsTherapist]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        raise PermissionDenied(SCHEDULE_ADMIN_MANAGED_MSG)


# ===========================================================================
# Public catalog
# ===========================================================================


class SessionTypeViewSet(viewsets.ModelViewSet):
    """Session-type catalog. Public sees active types; admin sees all."""

    queryset = SessionType.objects.all()
    serializer_class = SessionTypeSerializer
    lookup_field = "slug"
    permission_classes = [IsPsyAdminOrReadOnly]

    def get_queryset(self):
        qs = super().get_queryset().filter(institute=request_institute(self.request, "booking"))
        if self.action in ("list", "retrieve") and not _is_clinic_admin(self.request.user):
            return qs.filter(is_active=True)
        return qs

    def perform_create(self, serializer):
        serializer.save(institute=request_institute(self.request, "booking"))


class TherapistProfileViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Public therapist directory plus open slots for booking."""

    serializer_class = TherapistProfileSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        institute = request_institute(self.request, "booking")
        return (
            TherapistProfile.objects.filter(
                is_active=True,
                is_accepting_patients=True,
                provider__institute=institute,
            )
            .select_related("provider")
            .annotate(
                rating_avg=Avg("provider__shared_reviews__rating"),
                rating_count=Count("provider__shared_reviews", distinct=True),
            )
        )

    @action(detail=True, methods=["get"], url_path="reviews")
    def reviews(self, request, pk=None):
        therapist = self.get_object()
        from apps.modules.reviews.models import Review
        from apps.modules.reviews.services import reviews_for_target

        if therapist.provider_id is None:
            return Response([])
        qs = (
            reviews_for_target(therapist.provider.institute, therapist.provider)
            .filter(text_status=Review.TextStatus.APPROVED)
            .exclude(body="")
            .select_related("psy_context__patient__user")
            .order_by("-created_at")
        )
        return Response(PublicTherapistReviewSerializer(qs[:100], many=True).data)

    @action(detail=True, methods=["get"], url_path="slots")
    def slots(self, request, pk=None):
        therapist = self.get_object()
        qs = AppointmentSlot.objects.filter(
            therapist=therapist,
            status=AppointmentSlot.Status.OPEN,
            appointment__isnull=True,
            starts_at__gte=timezone.now(),
        ).select_related("therapist")
        date_from = request.query_params.get("from")
        date_to = request.query_params.get("to")
        if date_from:
            qs = qs.filter(starts_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(starts_at__date__lte=date_to)
        return Response(AppointmentSlotSerializer(qs[:200], many=True).data)


# ===========================================================================
# Therapist portal — schedule (disabled) + leave
# ===========================================================================


class TherapistAvailabilityViewSet(AdminManagedScheduleMixin, viewsets.ModelViewSet):
    serializer_class = TherapistAvailabilitySerializer


class AvailabilityExceptionViewSet(AdminManagedScheduleMixin, viewsets.ModelViewSet):
    serializer_class = AvailabilityExceptionSerializer


class TherapistSessionOfferViewSet(AdminManagedScheduleMixin, viewsets.ModelViewSet):
    serializer_class = TherapistSessionOfferSerializer


class TherapistLeaveRequestViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """Therapist submits and cancels their own leave; admin approves elsewhere."""

    serializer_class = LeaveRequestSerializer
    permission_classes = [IsAuthenticated, IsTherapist]

    def get_queryset(self):
        return LeaveRequest.objects.filter(
            therapist=self.request.user.therapist_profile
        ).select_related("therapist")

    def create(self, request):
        ser = SubmitLeaveRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            leave = services.submit_leave_request(
                therapist=request.user.therapist_profile,
                starts_on=ser.validated_data["starts_on"],
                ends_on=ser.validated_data["ends_on"],
                reason=ser.validated_data["reason"],
                start_time=ser.validated_data.get("start_time"),
                end_time=ser.validated_data.get("end_time"),
            )
        except services.LeaveError as exc:
            return _detail(str(exc))
        return Response(LeaveRequestSerializer(leave).data, status=201)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        leave = get_object_or_404(self.get_queryset(), pk=pk)
        try:
            leave = services.cancel_leave_request(leave=leave)
        except services.LeaveError as exc:
            return _detail(str(exc))
        return Response(LeaveRequestSerializer(leave).data)


# ===========================================================================
# Therapist portal — patients
# ===========================================================================


class TherapistPatientViewSet(viewsets.GenericViewSet):
    """Patients who have booked with the authenticated therapist."""

    permission_classes = [IsAuthenticated, IsTherapist]
    lookup_url_kwarg = "pk"

    def list(self, request):
        therapist = request.user.therapist_profile
        patients = (
            PatientProfile.objects.filter(id__in=_therapist_patient_ids(therapist))
            .select_related("user")
            .order_by("user__username")
        )
        data = [_build_patient_summary(therapist, p) for p in patients]
        return Response(TherapistPatientSummarySerializer(data, many=True).data)

    def retrieve(self, request, pk=None):
        therapist = request.user.therapist_profile
        patient = get_object_or_404(
            PatientProfile.objects.select_related("user"),
            pk=pk,
            id__in=_therapist_patient_ids(therapist),
        )
        summary = _build_patient_summary(therapist, patient)
        recent_appointments = (
            Appointment.objects.filter(therapist=therapist, patient=patient)
            .select_related("service_type", "provider", "customer", "slot")
            .order_by("-starts_at")[:20]
        )
        recent_notes = (
            SessionNote.objects.filter(
                author=therapist, appointment__customer__patient_profile=patient
            )
            .select_related("appointment", "author")
            .order_by("-created_at")[:20]
        )
        recent_responses = (
            PsychometricResponse.objects.filter(
                respondent=patient.user, assigned_to=therapist.user
            )
            .select_related("form", "respondent", "version")
            .order_by("-submitted_at")[:20]
        )
        services.sync_expired_access_requests(
            FileAccessRequest.objects.filter(therapist=therapist, patient=patient)
        )
        full_access = services.has_full_file_access(
            therapist=therapist, patient=patient
        )
        reports_qs = ClinicalReport.objects.filter(patient=patient).select_related(
            "appointment", "appointment__service_type", "therapist", "patient__user"
        )
        if not full_access:
            reports_qs = reports_qs.filter(therapist=therapist)
        clinical_reports = reports_qs.order_by("-created_at")
        other_count = (
            ClinicalReport.objects.filter(patient=patient)
            .exclude(therapist=therapist)
            .count()
        )
        pending_request = (
            FileAccessRequest.objects.filter(
                therapist=therapist,
                patient=patient,
                status=FileAccessRequest.Status.PENDING,
            )
            .select_related("therapist", "patient__user", "granted_by")
            .first()
        )
        return Response(
            {
                **summary,
                "recent_appointments": AppointmentSerializer(
                    recent_appointments, many=True
                ).data,
                "recent_notes": SessionNoteSerializer(recent_notes, many=True).data,
                "recent_responses": PsychometricResponseSerializer(
                    recent_responses, many=True
                ).data,
                "clinical_reports": ClinicalReportSerializer(
                    clinical_reports, many=True
                ).data,
                "has_full_file_access": full_access,
                "pending_file_access_request": (
                    FileAccessRequestSerializer(pending_request).data
                    if pending_request
                    else None
                ),
                "other_therapists_report_count": other_count,
            }
        )


# ===========================================================================
# Appointments (patient / therapist / admin)
# ===========================================================================


class AppointmentViewSet(viewsets.GenericViewSet):
    """Book, pay, cancel, and inspect appointments.

    Queryset is scoped by role: admin sees all, therapist sees theirs,
    patient sees theirs. List without ``?page=`` stays a flat array for
    existing portals; ``?page=`` returns a paginated envelope.
    """

    serializer_class = AppointmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = Appointment.objects.filter(
            institute=request_institute(self.request, "booking")
        ).select_related(
            "patient__user", "therapist", "session_type", "slot"
        )
        if _is_clinic_admin(user):
            return qs
        therapist = _therapist_profile(user)
        if therapist:
            return qs.filter(therapist=therapist)
        patient = _patient_profile(user)
        if patient:
            return qs.filter(patient=patient)
        return qs.none()

    def _filtered_queryset(self, request):
        qs = self.get_queryset().order_by("-starts_at")
        therapist = request.query_params.get("therapist")
        patient = request.query_params.get("patient")
        status_param = request.query_params.get("status")
        date_from = request.query_params.get("from")
        date_to = request.query_params.get("to")
        if therapist:
            qs = qs.filter(therapist_id=therapist)
        if patient:
            qs = qs.filter(patient_id=patient)
        if status_param:
            qs = qs.filter(status=status_param)
        if date_from:
            qs = qs.filter(starts_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(starts_at__date__lte=date_to)
        return qs

    def list(self, request):
        qs = self._filtered_queryset(request)
        page_raw = request.query_params.get("page")
        if page_raw is None:
            return Response(_appointment_payload(qs[:100], request, many=True))

        try:
            page = max(1, int(page_raw))
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = min(100, max(1, int(request.query_params.get("page_size", 25))))
        except (TypeError, ValueError):
            page_size = 25

        total = qs.count()
        start = (page - 1) * page_size
        items = qs[start : start + page_size]
        return Response(
            {
                "count": total,
                "page": page,
                "page_size": page_size,
                "results": _appointment_payload(items, request, many=True),
            }
        )

    def retrieve(self, request, pk=None):
        appt = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(_appointment_payload(appt, request))

    def create(self, request):
        patient = _patient_profile(request.user)
        if not patient:
            return _detail("Patient profile required.")
        ser = BookAppointmentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            appt = services.book_slot(
                patient=patient,
                slot_id=ser.validated_data["slot_id"],
                session_type_id=ser.validated_data["session_type_id"],
            )
        except AppointmentSlot.DoesNotExist:
            return _detail("Slot not found.", 404)
        except services.BookingError as exc:
            return _detail(str(exc))
        return Response(_appointment_payload(appt, request), status=201)

    @action(detail=True, methods=["post"])
    def confirm_payment(self, request, pk=None):
        appt = get_object_or_404(self.get_queryset(), pk=pk)
        patient = _patient_profile(request.user)
        owns_appointment = patient and appt.patient_id == patient.id
        if not owns_appointment and not _is_clinic_admin(request.user):
            return _forbidden()
        ser = ConfirmAppointmentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            appt = services.confirm_appointment_payment(
                appointment=appt,
                payment_ref=ser.validated_data["payment_ref"],
                idempotency_key=ser.validated_data["idempotency_key"],
            )
        except services.BookingError as exc:
            return _detail(str(exc))
        except Exception as exc:
            # Finance app raises domain errors that are not BookingError.
            return _detail(str(exc))
        return Response(_appointment_payload(appt, request))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        appt = get_object_or_404(self.get_queryset(), pk=pk)
        ser = CancelAppointmentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        therapist = _therapist_profile(request.user)
        patient = _patient_profile(request.user)
        if _is_clinic_admin(request.user):
            role = "admin"
        elif therapist and appt.therapist_id == therapist.id:
            return _forbidden(
                "Therapists cannot cancel appointments. Submit a leave request."
            )
        elif patient and appt.patient_id == patient.id:
            role = "patient"
        else:
            return _forbidden()

        try:
            appt = services.cancel_appointment(
                appointment=appt,
                canceled_by=role,
                reason=ser.validated_data.get("reason", ""),
            )
        except services.BookingError as exc:
            return _detail(str(exc))
        return Response(_appointment_payload(appt, request))

    @action(detail=True, methods=["post"])
    def set_meeting_link(self, request, pk=None):
        appt = get_object_or_404(self.get_queryset(), pk=pk)
        if not _is_clinic_admin(request.user):
            return _forbidden()
        ser = SetMeetingLinkSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        appt.meeting_link = ser.validated_data.get("meeting_link", "") or ""
        appt.save(update_fields=["meeting_link", "updated_at"])
        return Response(_appointment_payload(appt, request))

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        appt = get_object_or_404(self.get_queryset(), pk=pk)
        therapist = _therapist_profile(request.user)
        is_owner_therapist = therapist and appt.therapist_id == therapist.id
        if not (is_owner_therapist or _is_clinic_admin(request.user)):
            return _forbidden()
        try:
            appt = services.complete_appointment(appointment=appt)
        except services.BookingError as exc:
            return _detail(str(exc))
        return Response(_appointment_payload(appt, request))

    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        appt = get_object_or_404(Appointment.objects.all(), pk=pk)
        patient = _patient_profile(request.user)
        if not patient or appt.patient_id != patient.id:
            return _forbidden()
        ser = SubmitTherapistReviewSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            review = services.create_review(
                appointment=appt,
                patient=patient,
                rating=ser.validated_data["rating"],
                body=ser.validated_data.get("body", ""),
            )
        except services.ReviewError as exc:
            return _detail(str(exc))
        return Response(
            TherapistReviewSerializer(review, context={"request": request}).data,
            status=201,
        )

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsPsyAdmin])
    def move(self, request, pk=None):
        appt = get_object_or_404(Appointment.objects.all(), pk=pk)
        ser = MoveAppointmentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            appt = services.move_appointment(
                appointment=appt, new_slot_id=ser.validated_data["new_slot_id"]
            )
        except services.BookingError as exc:
            return _detail(str(exc))
        except AppointmentSlot.DoesNotExist:
            return _detail("Slot not found.", 404)
        return Response(_appointment_payload(appt, request))


class TherapistReviewListView(APIView):
    """Therapist sees own ratings; comment text only after admin approval."""

    permission_classes = [IsAuthenticated, IsTherapist]

    def get(self, request):
        from apps.modules.reviews.services import reviews_for_target

        therapist = request.user.therapist_profile
        target = therapist.provider
        if target is None:
            return Response([])
        qs = (
            reviews_for_target(target.institute, target)
            .select_related("psy_context__patient__user")
            .order_by("-created_at")
        )
        return Response(
            TherapistReviewSerializer(
                qs[:200], many=True, context={"request": request}
            ).data
        )


class RegenerateSlotsView(APIView):
    """Admin: rebuild open slots for a therapist over a date range."""

    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def post(self, request):
        ser = RegenerateSlotsSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        therapist = get_object_or_404(
            TherapistProfile, pk=ser.validated_data["therapist_id"]
        )
        created = services.regenerate_slots_for_therapist(
            therapist=therapist,
            range_start=ser.validated_data["range_start"],
            range_end=ser.validated_data["range_end"],
        )
        return Response({"created": created})


# ===========================================================================
# Session notes
# ===========================================================================


class SessionNoteViewSet(viewsets.ModelViewSet):
    """Therapist authors notes; patients only see notes shared with them."""

    serializer_class = SessionNoteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = SessionNote.objects.select_related("appointment", "author")
        if _is_clinic_admin(user):
            return qs
        therapist = _therapist_profile(user)
        if therapist:
            return qs.filter(author=therapist)
        patient = _patient_profile(user)
        if patient:
            return qs.filter(
                appointment__customer__patient_profile=patient,
                shared_with_patient=True,
            )
        return qs.none()

    def perform_create(self, serializer):
        therapist = self.request.user.therapist_profile
        appointment = serializer.validated_data["appointment"]
        if appointment.therapist_id != therapist.id:
            raise serializers.ValidationError("Not your appointment.")
        serializer.save(author=therapist)


# ===========================================================================
# Clinical reports & file access (private EHR)
# ===========================================================================


class ClinicalReportViewSet(viewsets.ModelViewSet):
    """Private clinical reports. Patients never see this collection."""

    serializer_class = ClinicalReportSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), IsTherapist()]
        return super().get_permissions()

    def get_queryset(self):
        user = self.request.user
        qs = ClinicalReport.objects.select_related(
            "appointment",
            "appointment__service_type",
            "therapist",
            "patient__user",
        )
        if _is_clinic_admin(user):
            return qs
        therapist = _therapist_profile(user)
        if therapist:
            granted_ids = services.patients_with_full_file_access(therapist=therapist)
            return qs.filter(Q(therapist=therapist) | Q(patient_id__in=granted_ids))
        return qs.none()

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            report = services.submit_clinical_report(
                therapist=request.user.therapist_profile,
                appointment=ser.validated_data["appointment"],
                summary=ser.validated_data["summary"],
                assessment=ser.validated_data["assessment"],
                treatment_plan=ser.validated_data["treatment_plan"],
                risk_flags=ser.validated_data.get("risk_flags") or [],
            )
        except services.ClinicalRecordError as exc:
            return _detail(str(exc))
        out = ClinicalReportSerializer(report, context={"request": request})
        return Response(out.data, status=201)

    def perform_update(self, serializer):
        user = self.request.user
        report = serializer.instance
        therapist = _therapist_profile(user)
        if not _is_clinic_admin(user) and (
            not therapist or report.therapist_id != therapist.id
        ):
            raise PermissionDenied("You can only edit your own clinical reports.")
        serializer.save()

    @action(detail=False, methods=["get"], url_path="missing")
    def missing(self, request):
        user = request.user
        therapist = None
        if not _is_clinic_admin(user):
            therapist = _therapist_profile(user)
            if not therapist:
                return _forbidden()
        items = services.missing_report_appointments(therapist=therapist)
        data = MissingReportAppointmentSerializer(items, many=True).data
        return Response({"count": len(data), "items": data})


class FileAccessRequestViewSet(viewsets.GenericViewSet):
    """Therapist requests temporary master-file access; admin approves."""

    serializer_class = FileAccessRequestSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), IsTherapist()]
        if self.action in ("approve", "reject"):
            return [IsAuthenticated(), IsPsyAdmin()]
        return super().get_permissions()

    def get_queryset(self):
        services.sync_expired_access_requests()
        user = self.request.user
        qs = FileAccessRequest.objects.select_related(
            "therapist", "patient__user", "granted_by"
        )
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        if _is_clinic_admin(user):
            return qs
        therapist = _therapist_profile(user)
        if therapist:
            return qs.filter(therapist=therapist)
        return qs.none()

    def list(self, request):
        qs = self.get_queryset()
        return Response(FileAccessRequestSerializer(qs[:200], many=True).data)

    def retrieve(self, request, pk=None):
        row = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(FileAccessRequestSerializer(row).data)

    def create(self, request):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            row = services.submit_file_access_request(
                therapist=request.user.therapist_profile,
                patient=ser.validated_data["patient"],
                reason=ser.validated_data.get("reason", ""),
            )
        except services.ClinicalRecordError as exc:
            return _detail(str(exc))
        return Response(
            FileAccessRequestSerializer(row).data,
            status=201,
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        row = get_object_or_404(FileAccessRequest, pk=pk)
        ser = ApproveFileAccessSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            row = services.approve_file_access_request(
                request=row,
                admin_user=request.user,
                access_days=ser.validated_data.get("access_days", 7),
            )
        except services.ClinicalRecordError as exc:
            return _detail(str(exc))
        return Response(FileAccessRequestSerializer(row).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        row = get_object_or_404(FileAccessRequest, pk=pk)
        ser = RejectFileAccessSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            row = services.reject_file_access_request(
                request=row,
                admin_user=request.user,
                decision_note=ser.validated_data.get("decision_note", ""),
            )
        except services.ClinicalRecordError as exc:
            return _detail(str(exc))
        return Response(FileAccessRequestSerializer(row).data)


# ===========================================================================
# Psychometrics
# ===========================================================================


class PsychometricFormViewSet(viewsets.ModelViewSet):
    """Form catalog. Public/patient sees published forms; admin sees drafts."""

    queryset = PsychometricForm.objects.all()
    serializer_class = PsychometricFormSerializer
    lookup_field = "slug"
    permission_classes = [IsPsyAdminOrReadOnly]

    def get_queryset(self):
        qs = super().get_queryset().filter(institute__slug="psy")
        if self.action in ("list", "retrieve", "submit") and not _is_clinic_admin(
            self.request.user
        ):
            return qs.filter(is_published=True)
        return qs

    def perform_create(self, serializer):
        from apps.modules.forms.services import publish_schema
        from apps.kernel.tenancy.models import Institute

        form = serializer.save(
            created_by=self.request.user,
            institute=Institute.objects.get(slug="psy"),
        )
        publish_schema(form=form, schema=form.schema)

    def perform_update(self, serializer):
        from apps.modules.forms.services import publish_schema

        schema = serializer.validated_data.get("schema", serializer.instance.schema)
        form = serializer.save()
        publish_schema(form=form, schema=schema)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsPatient])
    def submit(self, request, slug=None):
        form = self.get_object()
        ser = SubmitPsychometricSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        assigned_to = None
        tid = ser.validated_data.get("routed_therapist_id")
        if tid:
            assigned_to = get_object_or_404(TherapistProfile, pk=tid).user
        response = submit_form_response(
            form=form,
            respondent=request.user,
            answers=ser.validated_data["answers"],
            assigned_to=assigned_to,
        )
        return Response(PsychometricResponseSerializer(response).data, status=201)


class PsychometricResponseViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Submitted answers: patient owns theirs; therapist sees routed ones."""

    serializer_class = PsychometricResponseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = PsychometricResponse.objects.filter(institute__slug="psy").select_related(
            "form", "respondent", "version"
        )
        if _is_clinic_admin(user):
            return qs
        therapist = _therapist_profile(user)
        if therapist:
            return qs.filter(assigned_to=therapist.user)
        patient = _patient_profile(user)
        if patient:
            return qs.filter(respondent=patient.user)
        return qs.none()


class TherapistFinanceView(APIView):
    """Read-only earnings for the authenticated therapist.

    Sums snapshotted appointment prices for this therapist only.
    Clinic-wide ledger / SEP figures are never included.
    """

    permission_classes = [IsAuthenticated, IsTherapist]

    def get(self, request):
        start_date, end_date, error = _parse_therapist_finance_range(request)
        if error:
            return _detail(error)
        report = services.therapist_finance_report(
            therapist=request.user.therapist_profile,
            start_date=start_date,
            end_date=end_date,
        )
        return Response(TherapistFinanceReportSerializer(report).data)


def _parse_therapist_finance_range(request) -> tuple[date, date, str | None]:
    today = timezone.localdate()
    raw_start = request.query_params.get("start_date")
    raw_end = request.query_params.get("end_date")
    if raw_start:
        start_date = parse_date(raw_start)
        if start_date is None:
            return today, today, "Invalid start_date. Use YYYY-MM-DD."
    else:
        start_date = today.replace(day=1)
    if raw_end:
        end_date = parse_date(raw_end)
        if end_date is None:
            return today, today, "Invalid end_date. Use YYYY-MM-DD."
    else:
        last_day = monthrange(today.year, today.month)[1]
        end_date = today.replace(day=last_day)
    if start_date > end_date:
        return today, today, "start_date must be on or before end_date."
    return start_date, end_date, None

# ===========================================================================
# Support tickets
# ===========================================================================


class TicketViewSet(viewsets.GenericViewSet):
    """Patient support / withdrawal tickets. Admin sees all; patient sees own."""

    permission_classes = [IsAuthenticated]
    serializer_class = TicketSerializer

    def get_queryset(self):
        user = self.request.user
        qs = Ticket.objects.prefetch_related("messages")
        if _is_clinic_admin(user):
            return qs
        patient = _patient_profile(user)
        if patient:
            return qs.filter(patient=patient)
        return qs.none()

    def list(self, request):
        return Response(TicketSerializer(self.get_queryset()[:50], many=True).data)

    def retrieve(self, request, pk=None):
        ticket = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(TicketSerializer(ticket).data)

    def create(self, request):
        patient = _patient_profile(request.user)
        if not patient:
            return _detail("Patient profile required.")
        ser = CreateTicketSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        with transaction.atomic():
            ticket = Ticket.objects.create(
                patient=patient,
                type=data["type"],
                subject=data["subject"],
                bank_details_snapshot=data.get("bank_details") or {},
            )
            TicketMessage.objects.create(
                ticket=ticket,
                author=request.user,
                body=data["body"],
                is_staff_reply=False,
            )
            if data["type"] == Ticket.Type.WITHDRAWAL:
                amount = data.get("withdrawal_amount")
                bank = data.get("bank_details")
                key = data.get("idempotency_key") or f"ticket-wd:{ticket.pk}"
                if not amount or not bank:
                    return _detail("withdrawal_amount and bank_details required.")
                try:
                    withdrawal = finance_services.create_withdrawal(
                        user=request.user,
                        amount=amount,
                        bank_details=bank,
                        ticket_reference=f"psy.ticket:{ticket.pk}",
                        idempotency_key=key,
                    )
                except finance_services.FinanceError as exc:
                    return _detail(str(exc))
                ticket.withdrawal_ref = f"finance.withdrawal:{withdrawal.pk}"
                ticket.save(update_fields=["withdrawal_ref", "updated_at"])

        return Response(TicketSerializer(ticket).data, status=201)

    @action(detail=True, methods=["post"])
    def messages(self, request, pk=None):
        ticket = get_object_or_404(self.get_queryset(), pk=pk)
        body = request.data.get("body", "").strip()
        if not body:
            return _detail("body required")
        is_staff = _is_clinic_admin(request.user)
        msg = TicketMessage.objects.create(
            ticket=ticket,
            author=request.user,
            body=body,
            is_staff_reply=is_staff,
        )
        if is_staff and ticket.status == Ticket.Status.OPEN:
            ticket.status = Ticket.Status.IN_PROGRESS
            ticket.save(update_fields=["status", "updated_at"])
        return Response(TicketMessageSerializer(msg).data, status=201)


# ===========================================================================
# Bootstrap
# ===========================================================================


class EnsurePsyGroupsView(APIView):
    """Idempotent helper for bootstrapping role groups (admin-only)."""

    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def post(self, request):
        created = []
        for name in PSY_ROLE_GROUPS:
            _, was_created = Group.objects.get_or_create(name=name)
            if was_created:
                created.append(name)
        return Response({"created": created})
