"""Admin-owned scheduling: templates, one-off slots, on-behalf booking, leave review."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.finance.services import FinanceError, InsufficientFunds

from . import services
from .models import (
    AppointmentSlot,
    AvailabilityException,
    LeaveRequest,
    PatientProfile,
    TherapistAvailability,
    TherapistProfile,
    TherapistSessionOffer,
)
from .permissions import IsPsyAdmin
from .serializers import (
    AdminAppointmentSlotSerializer,
    AdminBookAppointmentSerializer,
    AdminCreateSlotSerializer,
    AppointmentSerializer,
    AvailabilityExceptionSerializer,
    LeaveRequestSerializer,
    LeaveReviewSerializer,
    TherapistAvailabilitySerializer,
    TherapistSessionOfferSerializer,
)


class _AdminScheduleMixin:
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def _therapist(self, therapist_id: int) -> TherapistProfile:
        return get_object_or_404(TherapistProfile, pk=therapist_id)


_PERSIAN_WEEKDAY_ORDER = {5: 0, 6: 1, 0: 2, 1: 3, 2: 4, 3: 5, 4: 6}


class AdminTherapistAvailabilityListCreate(_AdminScheduleMixin, APIView):
    def get(self, request, therapist_id: int):
        qs = TherapistAvailability.objects.filter(therapist_id=therapist_id)
        rows = sorted(
            qs,
            key=lambda row: (
                _PERSIAN_WEEKDAY_ORDER.get(row.weekday, 99),
                row.start_time,
            ),
        )
        return Response(TherapistAvailabilitySerializer(rows, many=True).data)

    def post(self, request, therapist_id: int):
        therapist = self._therapist(therapist_id)
        ser = TherapistAvailabilitySerializer(
            data=request.data, context={"therapist": therapist}
        )
        ser.is_valid(raise_exception=True)
        ser.save(therapist=therapist)
        return Response(ser.data, status=201)


class AdminTherapistAvailabilityDetail(_AdminScheduleMixin, APIView):
    def _obj(self, therapist_id: int, pk: int) -> TherapistAvailability:
        return get_object_or_404(
            TherapistAvailability, pk=pk, therapist_id=therapist_id
        )

    def patch(self, request, therapist_id: int, pk: int):
        obj = self._obj(therapist_id, pk)
        ser = TherapistAvailabilitySerializer(
            obj, data=request.data, partial=True, context={"therapist": obj.therapist}
        )
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)

    def delete(self, request, therapist_id: int, pk: int):
        self._obj(therapist_id, pk).delete()
        return Response(status=204)


class AdminTherapistOfferListCreate(_AdminScheduleMixin, APIView):
    def get(self, request, therapist_id: int):
        qs = TherapistSessionOffer.objects.filter(
            therapist_id=therapist_id
        ).select_related("session_type")
        return Response(TherapistSessionOfferSerializer(qs, many=True).data)

    def post(self, request, therapist_id: int):
        therapist = self._therapist(therapist_id)
        ser = TherapistSessionOfferSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save(therapist=therapist)
        return Response(TherapistSessionOfferSerializer(ser.instance).data, status=201)


class AdminTherapistOfferDetail(_AdminScheduleMixin, APIView):
    def _obj(self, therapist_id: int, pk: int) -> TherapistSessionOffer:
        return get_object_or_404(
            TherapistSessionOffer.objects.select_related("session_type"),
            pk=pk,
            therapist_id=therapist_id,
        )

    def patch(self, request, therapist_id: int, pk: int):
        obj = self._obj(therapist_id, pk)
        ser = TherapistSessionOfferSerializer(obj, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(TherapistSessionOfferSerializer(ser.instance).data)

    def delete(self, request, therapist_id: int, pk: int):
        self._obj(therapist_id, pk).delete()
        return Response(status=204)


class AdminTherapistExceptionListCreate(_AdminScheduleMixin, APIView):
    def get(self, request, therapist_id: int):
        qs = AvailabilityException.objects.filter(therapist_id=therapist_id).order_by(
            "-date"
        )
        return Response(AvailabilityExceptionSerializer(qs, many=True).data)

    def post(self, request, therapist_id: int):
        therapist = self._therapist(therapist_id)
        ser = AvailabilityExceptionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save(therapist=therapist)
        return Response(ser.data, status=201)


class AdminTherapistExceptionDetail(_AdminScheduleMixin, APIView):
    def delete(self, request, therapist_id: int, pk: int):
        obj = get_object_or_404(
            AvailabilityException, pk=pk, therapist_id=therapist_id
        )
        obj.delete()
        return Response(status=204)


class AdminSlotListCreateView(_AdminScheduleMixin, APIView):
    def get(self, request):
        raw_from = request.query_params.get("from")
        raw_to = request.query_params.get("to")
        date_from = parse_date(raw_from) if raw_from else None
        date_to = parse_date(raw_to) if raw_to else None
        if not date_from or not date_to:
            return Response({"detail": "from and to query params are required."}, status=400)
        qs = AppointmentSlot.objects.select_related(
            "therapist", "session_type", "appointment", "appointment__patient__user"
        ).order_by("starts_at")
        therapist = request.query_params.get("therapist")
        status_param = request.query_params.get("status")
        if therapist:
            qs = qs.filter(therapist_id=therapist)
        if status_param:
            qs = qs.filter(status=status_param)
        qs = qs.filter(starts_at__date__gte=date_from, starts_at__date__lte=date_to)
        return Response(AdminAppointmentSlotSerializer(qs[:500], many=True).data)

    def post(self, request):
        ser = AdminCreateSlotSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        therapist = get_object_or_404(
            TherapistProfile, pk=ser.validated_data["therapist_id"]
        )
        try:
            slot = services.create_open_slot(
                therapist=therapist,
                starts_at=ser.validated_data["starts_at"],
                ends_at=ser.validated_data["ends_at"],
            )
        except services.SlotError as exc:
            return Response({"detail": str(exc)}, status=409)
        slot = AppointmentSlot.objects.select_related(
            "therapist", "session_type"
        ).get(pk=slot.pk)
        return Response(AdminAppointmentSlotSerializer(slot).data, status=201)


class AdminSlotDetailView(_AdminScheduleMixin, APIView):
    def delete(self, request, pk: int):
        slot = get_object_or_404(AppointmentSlot, pk=pk)
        try:
            services.delete_open_slot(slot=slot)
        except services.SlotError as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(status=204)


class AdminAppointmentCreateView(_AdminScheduleMixin, APIView):
    def post(self, request):
        ser = AdminBookAppointmentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        patient = get_object_or_404(PatientProfile, pk=ser.validated_data["patient_id"])
        try:
            appt = services.admin_book_appointment(
                patient=patient,
                slot_id=ser.validated_data["slot_id"],
                session_type_id=ser.validated_data["session_type_id"],
                payment=ser.validated_data["payment"],
            )
        except AppointmentSlot.DoesNotExist:
            return Response({"detail": "Slot not found."}, status=404)
        except (services.BookingError, InsufficientFunds, FinanceError) as exc:
            return Response({"detail": str(exc)}, status=400)
        appt = appt.__class__.objects.select_related(
            "patient__user", "therapist", "session_type", "slot"
        ).get(pk=appt.pk)
        return Response(AppointmentSerializer(appt).data, status=201)


class AdminLeaveRequestListView(_AdminScheduleMixin, APIView):
    def get(self, request):
        qs = LeaveRequest.objects.select_related("therapist").order_by("-created_at")
        status_param = request.query_params.get("status")
        therapist = request.query_params.get("therapist")
        if status_param:
            qs = qs.filter(status=status_param)
        if therapist:
            qs = qs.filter(therapist_id=therapist)
        return Response(LeaveRequestSerializer(qs[:200], many=True).data)


class AdminLeaveRequestApproveView(_AdminScheduleMixin, APIView):
    def post(self, request, pk: int):
        leave = get_object_or_404(LeaveRequest, pk=pk)
        ser = LeaveReviewSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            leave, created, conflicts = services.approve_leave_request(
                leave=leave,
                reviewer=request.user,
                admin_note=ser.validated_data.get("admin_note", ""),
            )
        except services.LeaveError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(
            {
                "leave_request": LeaveRequestSerializer(leave).data,
                "slots_created": created,
                "conflicts": AppointmentSerializer(conflicts, many=True).data,
            }
        )


class AdminLeaveRequestRejectView(_AdminScheduleMixin, APIView):
    def post(self, request, pk: int):
        leave = get_object_or_404(LeaveRequest, pk=pk)
        ser = LeaveReviewSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            leave = services.reject_leave_request(
                leave=leave,
                reviewer=request.user,
                admin_note=ser.validated_data.get("admin_note", ""),
            )
        except services.LeaveError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(LeaveRequestSerializer(leave).data)
