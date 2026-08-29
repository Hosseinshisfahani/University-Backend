from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.finance import services as finance_services
from apps.finance.models import LedgerEntry

from . import services
from .models import (
    Appointment,
    AppointmentSlot,
    BlogPost,
    LeaveRequest,
    PatientProfile,
    PsychometricForm,
    PsychometricResponse,
    SessionNote,
    SessionType,
    SitePage,
    TherapistProfile,
    TherapistSessionOffer,
    Ticket,
    TicketMessage,
    Workshop,
    WorkshopEnrollment,
    WorkshopResource,
    WorkshopSession,
)
from .permissions import IsPatient, IsPsyAdmin, IsPsyAdminOrReadOnly, IsTherapist
from .serializers import (
    AppointmentSerializer,
    AppointmentSlotSerializer,
    AvailabilityExceptionSerializer,
    BlogPostSerializer,
    BookAppointmentSerializer,
    CancelAppointmentSerializer,
    CancelWorkshopEnrollmentSerializer,
    ConfirmAppointmentSerializer,
    ConfirmWorkshopEnrollmentSerializer,
    CreateTicketSerializer,
    LeaveRequestSerializer,
    MoveAppointmentSerializer,
    PsychometricFormSerializer,
    PsychometricResponseSerializer,
    RegenerateSlotsSerializer,
    SessionNoteSerializer,
    SessionTypeSerializer,
    SetMeetingLinkSerializer,
    SitePageSerializer,
    SubmitLeaveRequestSerializer,
    SubmitPsychometricSerializer,
    TherapistAvailabilitySerializer,
    TherapistPatientSummarySerializer,
    TherapistProfileSerializer,
    TherapistSessionOfferSerializer,
    TicketMessageSerializer,
    TicketSerializer,
    WorkshopCertificateSerializer,
    WorkshopDetailSerializer,
    WorkshopEnrollmentSerializer,
    WorkshopResourceWriteSerializer,
    WorkshopSerializer,
    WorkshopSessionWriteSerializer,
)


class SessionTypeViewSet(viewsets.ModelViewSet):
    queryset = SessionType.objects.all()
    serializer_class = SessionTypeSerializer
    lookup_field = "slug"
    permission_classes = [IsPsyAdminOrReadOnly]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action in ("list", "retrieve") and not (
            self.request.user.is_authenticated
            and (self.request.user.is_staff or self.request.user.groups.filter(name="psy_admin").exists())
        ):
            return qs.filter(is_active=True)
        return qs


class TherapistProfileViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = TherapistProfile.objects.filter(
        is_active=True, is_accepting_patients=True
    ).prefetch_related(
        Prefetch(
            "session_offers",
            queryset=TherapistSessionOffer.objects.filter(
                is_active=True, session_type__is_active=True
            ).select_related("session_type"),
            to_attr="active_offers",
        )
    )
    serializer_class = TherapistProfileSerializer
    permission_classes = [AllowAny]

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


class TherapistAvailabilityViewSet(viewsets.ModelViewSet):
    serializer_class = TherapistAvailabilitySerializer
    permission_classes = [IsAuthenticated, IsTherapist]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        raise PermissionDenied("Therapist schedule is managed by clinic admin.")


class AvailabilityExceptionViewSet(viewsets.ModelViewSet):
    serializer_class = AvailabilityExceptionSerializer
    permission_classes = [IsAuthenticated, IsTherapist]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        raise PermissionDenied("Therapist schedule is managed by clinic admin.")


class TherapistSessionOfferViewSet(viewsets.ModelViewSet):
    serializer_class = TherapistSessionOfferSerializer
    permission_classes = [IsAuthenticated, IsTherapist]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        raise PermissionDenied("Therapist schedule is managed by clinic admin.")


class TherapistLeaveRequestViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
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
            return Response({"detail": str(exc)}, status=400)
        return Response(LeaveRequestSerializer(leave).data, status=201)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        leave = get_object_or_404(self.get_queryset(), pk=pk)
        try:
            leave = services.cancel_leave_request(leave=leave)
        except services.LeaveError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(LeaveRequestSerializer(leave).data)


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
        author=therapist, appointment__patient=patient
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


class TherapistPatientViewSet(viewsets.GenericViewSet):
    """Unique patients who have booked with the authenticated therapist."""

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
            .select_related("session_type", "therapist", "patient", "slot")
            .order_by("-starts_at")[:20]
        )
        recent_notes = (
            SessionNote.objects.filter(author=therapist, appointment__patient=patient)
            .select_related("appointment", "author")
            .order_by("-created_at")[:20]
        )
        recent_responses = (
            PsychometricResponse.objects.filter(
                patient=patient, routed_therapist=therapist
            )
            .select_related("form", "patient", "patient__user", "routed_therapist")
            .order_by("-submitted_at")[:20]
        )
        payload = {
            **summary,
            "recent_appointments": AppointmentSerializer(
                recent_appointments, many=True
            ).data,
            "recent_notes": SessionNoteSerializer(recent_notes, many=True).data,
            "recent_responses": PsychometricResponseSerializer(
                recent_responses, many=True
            ).data,
        }
        # Nested collections are already rendered dicts; do not re-run ModelSerializers.
        return Response(payload)


class AppointmentViewSet(viewsets.GenericViewSet):
    serializer_class = AppointmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = Appointment.objects.select_related(
            "patient__user", "therapist", "session_type", "slot"
        )
        if user.is_staff or user.groups.filter(name="psy_admin").exists():
            return qs
        if hasattr(user, "therapist_profile"):
            return qs.filter(therapist=user.therapist_profile)
        if hasattr(user, "patient_profile"):
            return qs.filter(patient=user.patient_profile)
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
            # Backward-compatible flat list for patient/therapist portals.
            return Response(AppointmentSerializer(qs[:100], many=True).data)

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
                "results": AppointmentSerializer(items, many=True).data,
            }
        )

    def retrieve(self, request, pk=None):
        appt = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(AppointmentSerializer(appt).data)

    def create(self, request):
        if not hasattr(request.user, "patient_profile"):
            return Response({"detail": "Patient profile required."}, status=400)
        ser = BookAppointmentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            appt = services.book_slot(
                patient=request.user.patient_profile,
                slot_id=ser.validated_data["slot_id"],
                session_type_id=ser.validated_data["session_type_id"],
            )
        except AppointmentSlot.DoesNotExist:
            return Response({"detail": "Slot not found."}, status=404)
        except services.BookingError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(AppointmentSerializer(appt).data, status=201)

    @action(detail=True, methods=["post"])
    def confirm_payment(self, request, pk=None):
        appt = get_object_or_404(self.get_queryset(), pk=pk)
        if not (
            hasattr(request.user, "patient_profile")
            and appt.patient_id == request.user.patient_profile.id
        ) and not (request.user.is_staff or request.user.groups.filter(name="psy_admin").exists()):
            return Response({"detail": "Forbidden."}, status=403)
        ser = ConfirmAppointmentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            appt = services.confirm_appointment_payment(
                appointment=appt,
                payment_ref=ser.validated_data["payment_ref"],
                idempotency_key=ser.validated_data["idempotency_key"],
            )
        except services.BookingError as exc:
            return Response({"detail": str(exc)}, status=400)
        except Exception as exc:  # finance errors
            return Response({"detail": str(exc)}, status=400)
        return Response(AppointmentSerializer(appt).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        appt = get_object_or_404(self.get_queryset(), pk=pk)
        ser = CancelAppointmentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        if request.user.is_staff or request.user.groups.filter(name="psy_admin").exists():
            role = "admin"
        elif hasattr(request.user, "therapist_profile") and appt.therapist_id == request.user.therapist_profile.id:
            return Response(
                {
                    "detail": "Therapists cannot cancel appointments. Submit a leave request."
                },
                status=403,
            )
        elif hasattr(request.user, "patient_profile") and appt.patient_id == request.user.patient_profile.id:
            role = "patient"
        else:
            return Response({"detail": "Forbidden."}, status=403)

        try:
            appt = services.cancel_appointment(
                appointment=appt,
                canceled_by=role,
                reason=ser.validated_data.get("reason", ""),
            )
        except services.BookingError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(AppointmentSerializer(appt).data)

    @action(detail=True, methods=["post"])
    def set_meeting_link(self, request, pk=None):
        appt = get_object_or_404(self.get_queryset(), pk=pk)
        is_owner_therapist = (
            hasattr(request.user, "therapist_profile")
            and appt.therapist_id == request.user.therapist_profile.id
        )
        is_admin = request.user.is_staff or request.user.groups.filter(
            name="psy_admin"
        ).exists()
        if not (is_owner_therapist or is_admin):
            return Response({"detail": "Forbidden."}, status=403)
        ser = SetMeetingLinkSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        appt.meeting_link = ser.validated_data.get("meeting_link", "") or ""
        appt.save(update_fields=["meeting_link", "updated_at"])
        return Response(AppointmentSerializer(appt).data)

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
            return Response({"detail": str(exc)}, status=400)
        except AppointmentSlot.DoesNotExist:
            return Response({"detail": "Slot not found."}, status=404)
        return Response(AppointmentSerializer(appt).data)


class RegenerateSlotsView(APIView):
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


class SessionNoteViewSet(viewsets.ModelViewSet):
    serializer_class = SessionNoteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = SessionNote.objects.select_related("appointment", "author")
        if user.is_staff or user.groups.filter(name="psy_admin").exists():
            return qs
        if hasattr(user, "therapist_profile"):
            return qs.filter(author=user.therapist_profile)
        if hasattr(user, "patient_profile"):
            return qs.filter(
                appointment__patient=user.patient_profile,
                shared_with_patient=True,
            )
        return qs.none()

    def perform_create(self, serializer):
        therapist = self.request.user.therapist_profile
        appointment = serializer.validated_data["appointment"]
        if appointment.therapist_id != therapist.id:
            raise serializers.ValidationError("Not your appointment.")
        serializer.save(author=therapist)


class PsychometricFormViewSet(viewsets.ModelViewSet):
    queryset = PsychometricForm.objects.all()
    serializer_class = PsychometricFormSerializer
    lookup_field = "slug"
    permission_classes = [IsPsyAdminOrReadOnly]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action in ("list", "retrieve", "submit") and not (
            self.request.user.is_authenticated
            and (self.request.user.is_staff or self.request.user.groups.filter(name="psy_admin").exists())
        ):
            return qs.filter(is_published=True)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsPatient])
    def submit(self, request, slug=None):
        form = self.get_object()
        ser = SubmitPsychometricSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        therapist = None
        tid = ser.validated_data.get("routed_therapist_id")
        if tid:
            therapist = get_object_or_404(TherapistProfile, pk=tid)
        response = PsychometricResponse.objects.create(
            form=form,
            form_version=form.version,
            patient=request.user.patient_profile,
            answers=ser.validated_data["answers"],
            routed_therapist=therapist,
        )
        return Response(PsychometricResponseSerializer(response).data, status=201)


class PsychometricResponseViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = PsychometricResponseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = PsychometricResponse.objects.select_related(
            "form", "patient", "patient__user", "routed_therapist"
        )
        if user.is_staff or user.groups.filter(name="psy_admin").exists():
            return qs
        if hasattr(user, "therapist_profile"):
            return qs.filter(routed_therapist=user.therapist_profile)
        if hasattr(user, "patient_profile"):
            return qs.filter(patient=user.patient_profile)
        return qs.none()


class WorkshopViewSet(viewsets.ModelViewSet):
    queryset = Workshop.objects.select_related("instructor").all()
    serializer_class = WorkshopSerializer
    lookup_field = "slug"
    permission_classes = [IsPsyAdminOrReadOnly]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return WorkshopDetailSerializer
        return WorkshopSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        is_admin = user.is_authenticated and (
            user.is_staff or user.groups.filter(name="psy_admin").exists()
        )
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
            if hasattr(user, "therapist_profile"):
                qs = qs.filter(
                    Q(is_published=True) | Q(instructor=user.therapist_profile)
                )
            elif not is_admin:
                # Anonymous / patient: published only for retrieve;
                # complete/cert still need published workshop object.
                qs = qs.filter(is_published=True)
        if self.action == "list" and self.request.query_params.get("upcoming") == "1":
            qs = qs.filter(starts_at__gte=timezone.now())
        if self.action == "retrieve":
            qs = qs.prefetch_related("sessions__resources", "resources")
        return qs

    def _workshop_error_response(self, exc: services.WorkshopError):
        body = {"code": exc.code, "detail": str(exc), **exc.extra}
        status_code = 403 if exc.code in ("forbidden",) else 400
        return Response(body, status=status_code)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsPatient])
    def enroll(self, request, slug=None):
        workshop = self.get_object()
        try:
            enrollment = services.enroll_in_workshop(
                workshop=workshop,
                patient=request.user.patient_profile,
            )
        except services.WorkshopError as exc:
            return self._workshop_error_response(exc)
        return Response(
            WorkshopEnrollmentSerializer(enrollment).data,
            status=201,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path=r"enrollments/(?P<enrollment_id>[^/.]+)/confirm",
        permission_classes=[IsAuthenticated, IsPatient],
    )
    def confirm_enrollment(self, request, slug=None, enrollment_id=None):
        workshop = self.get_object()
        enrollment = get_object_or_404(
            WorkshopEnrollment,
            pk=enrollment_id,
            workshop=workshop,
            patient=request.user.patient_profile,
        )
        ser = ConfirmWorkshopEnrollmentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            enrollment = services.confirm_workshop_enrollment(
                enrollment=enrollment,
                payment_ref=ser.validated_data["payment_ref"],
                idempotency_key=ser.validated_data["idempotency_key"],
            )
        except services.WorkshopError as exc:
            return self._workshop_error_response(exc)
        return Response(WorkshopEnrollmentSerializer(enrollment).data)

    @action(
        detail=True,
        methods=["post"],
        url_path=r"enrollments/(?P<enrollment_id>[^/.]+)/cancel",
        permission_classes=[IsAuthenticated],
    )
    def cancel_enrollment(self, request, slug=None, enrollment_id=None):
        workshop = self.get_object()
        enrollment = get_object_or_404(
            WorkshopEnrollment.objects.select_related("patient__user", "workshop"),
            pk=enrollment_id,
            workshop=workshop,
        )
        is_admin = request.user.is_staff or request.user.groups.filter(
            name="psy_admin"
        ).exists()
        is_owner = (
            hasattr(request.user, "patient_profile")
            and enrollment.patient_id == request.user.patient_profile.id
        )
        if not (is_admin or is_owner):
            return Response({"detail": "Forbidden."}, status=403)

        ser = CancelWorkshopEnrollmentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            enrollment = services.cancel_workshop_enrollment(
                enrollment=enrollment,
                canceled_by="admin" if is_admin else "patient",
                reason=ser.validated_data.get("reason", ""),
            )
        except services.WorkshopError as exc:
            return self._workshop_error_response(exc)
        return Response(WorkshopEnrollmentSerializer(enrollment).data)

    @action(
        detail=True,
        methods=["get"],
        url_path="roster",
        permission_classes=[IsAuthenticated],
    )
    def roster(self, request, slug=None):
        workshop = self.get_object()
        is_admin = request.user.is_staff or request.user.groups.filter(
            name="psy_admin"
        ).exists()
        is_instructor = (
            hasattr(request.user, "therapist_profile")
            and workshop.instructor_id == request.user.therapist_profile.id
        )
        if not (is_admin or is_instructor):
            return Response({"detail": "Forbidden."}, status=403)
        if is_admin:
            workshop = get_object_or_404(Workshop, slug=slug)
        rows = (
            WorkshopEnrollment.objects.filter(
                workshop=workshop,
                status=WorkshopEnrollment.Status.ACTIVE,
            )
            .select_related("patient__user", "workshop__instructor")
            .order_by("enrolled_at")
        )
        return Response(WorkshopEnrollmentSerializer(rows, many=True).data)

    @action(
        detail=True,
        methods=["post"],
        url_path=r"sessions/(?P<session_id>[^/.]+)/complete",
        permission_classes=[IsAuthenticated, IsPatient],
    )
    def complete_session(self, request, slug=None, session_id=None):
        workshop = self.get_object()
        enrollment = services.get_active_enrollment(
            user=request.user, workshop=workshop
        )
        if not enrollment:
            return Response(
                {"code": "forbidden", "detail": "Active enrollment required."},
                status=403,
            )
        session = get_object_or_404(
            WorkshopSession, pk=session_id, workshop=workshop
        )
        try:
            services.mark_session_complete(enrollment=enrollment, session=session)
        except services.WorkshopError as exc:
            return self._workshop_error_response(exc)
        return Response(
            WorkshopDetailSerializer(workshop, context={"request": request}).data
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="certificate/issue",
        permission_classes=[IsAuthenticated, IsPatient],
    )
    def issue_certificate(self, request, slug=None):
        workshop = self.get_object()
        enrollment = services.get_active_enrollment(
            user=request.user, workshop=workshop
        )
        if not enrollment:
            return Response(
                {"code": "forbidden", "detail": "Active enrollment required."},
                status=403,
            )
        try:
            cert = services.issue_certificate(enrollment=enrollment)
        except services.WorkshopError as exc:
            return self._workshop_error_response(exc)
        return Response(WorkshopCertificateSerializer(cert).data, status=201)

    @action(
        detail=True,
        methods=["get"],
        url_path="certificate",
        permission_classes=[IsAuthenticated, IsPatient],
    )
    def get_certificate(self, request, slug=None):
        workshop = self.get_object()
        enrollment = services.get_active_enrollment(
            user=request.user, workshop=workshop
        )
        if not enrollment:
            return Response(
                {"code": "forbidden", "detail": "Active enrollment required."},
                status=403,
            )
        from .models import WorkshopCertificate

        cert = WorkshopCertificate.objects.filter(enrollment=enrollment).first()
        if not cert:
            return Response({"detail": "Certificate not issued yet."}, status=404)
        return Response(WorkshopCertificateSerializer(cert).data)


class WorkshopSessionListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def get(self, request, workshop_slug):
        workshop = get_object_or_404(Workshop, slug=workshop_slug)
        rows = workshop.sessions.all()
        return Response(WorkshopSessionWriteSerializer(rows, many=True).data)

    def post(self, request, workshop_slug):
        workshop = get_object_or_404(Workshop, slug=workshop_slug)
        ser = WorkshopSessionWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        session = WorkshopSession.objects.create(workshop=workshop, **ser.validated_data)
        return Response(WorkshopSessionWriteSerializer(session).data, status=201)


class WorkshopSessionDetailView(APIView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def patch(self, request, workshop_slug, pk):
        session = get_object_or_404(
            WorkshopSession, pk=pk, workshop__slug=workshop_slug
        )
        ser = WorkshopSessionWriteSerializer(session, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)

    def delete(self, request, workshop_slug, pk):
        session = get_object_or_404(
            WorkshopSession, pk=pk, workshop__slug=workshop_slug
        )
        session.delete()
        return Response(status=204)


class WorkshopResourceListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def get(self, request, workshop_slug):
        workshop = get_object_or_404(Workshop, slug=workshop_slug)
        rows = workshop.resources.select_related("session").all()
        return Response(WorkshopResourceWriteSerializer(rows, many=True).data)

    def post(self, request, workshop_slug):
        workshop = get_object_or_404(Workshop, slug=workshop_slug)
        ser = WorkshopResourceWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        session = ser.validated_data.get("session")
        if session and session.workshop_id != workshop.id:
            return Response(
                {"detail": "Session must belong to this workshop."}, status=400
            )
        resource = WorkshopResource.objects.create(
            workshop=workshop, **ser.validated_data
        )
        return Response(WorkshopResourceWriteSerializer(resource).data, status=201)


class WorkshopResourceDetailView(APIView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def patch(self, request, workshop_slug, pk):
        resource = get_object_or_404(
            WorkshopResource, pk=pk, workshop__slug=workshop_slug
        )
        ser = WorkshopResourceWriteSerializer(
            resource, data=request.data, partial=True
        )
        ser.is_valid(raise_exception=True)
        session = ser.validated_data.get("session", resource.session)
        if session and session.workshop_id != resource.workshop_id:
            return Response(
                {"detail": "Session must belong to this workshop."}, status=400
            )
        ser.save()
        return Response(ser.data)

    def delete(self, request, workshop_slug, pk):
        resource = get_object_or_404(
            WorkshopResource, pk=pk, workshop__slug=workshop_slug
        )
        resource.delete()
        return Response(status=204)


class PatientWorkshopEnrollmentView(APIView):
    permission_classes = [IsAuthenticated, IsPatient]

    def get(self, request):
        rows = (
            WorkshopEnrollment.objects.filter(patient=request.user.patient_profile)
            .exclude(status=WorkshopEnrollment.Status.CANCELED)
            .select_related("workshop__instructor", "patient__user")
            .order_by("-enrolled_at")
        )
        return Response(WorkshopEnrollmentSerializer(rows, many=True).data)


class TherapistWorkshopListView(APIView):
    permission_classes = [IsAuthenticated, IsTherapist]

    def get(self, request):
        qs = (
            Workshop.objects.filter(instructor=request.user.therapist_profile)
            .select_related("instructor")
            .order_by("-starts_at")
        )
        return Response(WorkshopSerializer(qs, many=True).data)


class BlogPostPagination(PageNumberPagination):
    page_size = 9
    page_size_query_param = "page_size"
    max_page_size = 50


class BlogPostViewSet(viewsets.ModelViewSet):
    queryset = BlogPost.objects.select_related(
        "author", "author__therapist_profile"
    ).all()
    serializer_class = BlogPostSerializer
    lookup_field = "slug"
    permission_classes = [IsPsyAdminOrReadOnly]
    pagination_class = BlogPostPagination

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action in ("list", "retrieve"):
            if not (
                self.request.user.is_authenticated
                and (
                    self.request.user.is_staff
                    or self.request.user.groups.filter(name="psy_admin").exists()
                )
            ):
                return qs.filter(is_published=True)
        return qs

    def _stamp_published_at(self, serializer):
        is_published = serializer.validated_data.get(
            "is_published",
            getattr(serializer.instance, "is_published", False)
            if serializer.instance
            else False,
        )
        published_at = serializer.validated_data.get(
            "published_at",
            getattr(serializer.instance, "published_at", None)
            if serializer.instance
            else None,
        )
        if is_published and published_at is None:
            serializer.validated_data["published_at"] = timezone.now()

    def perform_create(self, serializer):
        self._stamp_published_at(serializer)
        serializer.save(author=self.request.user)

    def perform_update(self, serializer):
        self._stamp_published_at(serializer)
        serializer.save()


class SitePageViewSet(viewsets.ModelViewSet):
    queryset = SitePage.objects.all()
    serializer_class = SitePageSerializer
    lookup_field = "key"
    permission_classes = [IsPsyAdminOrReadOnly]


class TicketViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = TicketSerializer

    def get_queryset(self):
        user = self.request.user
        qs = Ticket.objects.prefetch_related("messages")
        if user.is_staff or user.groups.filter(name="psy_admin").exists():
            return qs
        if hasattr(user, "patient_profile"):
            return qs.filter(patient=user.patient_profile)
        return qs.none()

    def list(self, request):
        return Response(TicketSerializer(self.get_queryset()[:50], many=True).data)

    def retrieve(self, request, pk=None):
        ticket = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(TicketSerializer(ticket).data)

    def create(self, request):
        if not hasattr(request.user, "patient_profile"):
            return Response({"detail": "Patient profile required."}, status=400)
        ser = CreateTicketSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        patient = request.user.patient_profile

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
                    return Response(
                        {"detail": "withdrawal_amount and bank_details required."},
                        status=400,
                    )
                try:
                    withdrawal = finance_services.create_withdrawal(
                        user=request.user,
                        amount=amount,
                        bank_details=bank,
                        ticket_reference=f"psy.ticket:{ticket.pk}",
                        idempotency_key=key,
                    )
                except finance_services.FinanceError as exc:
                    return Response({"detail": str(exc)}, status=400)
                ticket.withdrawal_ref = f"finance.withdrawal:{withdrawal.pk}"
                ticket.save(update_fields=["withdrawal_ref", "updated_at"])

        return Response(TicketSerializer(ticket).data, status=201)

    @action(detail=True, methods=["post"])
    def messages(self, request, pk=None):
        ticket = get_object_or_404(self.get_queryset(), pk=pk)
        body = request.data.get("body", "").strip()
        if not body:
            return Response({"detail": "body required"}, status=400)
        is_staff = request.user.is_staff or request.user.groups.filter(name="psy_admin").exists()
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


class EnsurePsyGroupsView(APIView):
    """Idempotent helper for bootstrapping role groups (admin-only)."""

    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def post(self, request):
        created = []
        for name in ("psy_admin", "psy_therapist", "psy_patient"):
            _, was_created = Group.objects.get_or_create(name=name)
            if was_created:
                created.append(name)
        return Response({"created": created})
