"""Admin-only aggregate API views for the Psychology Institute portal."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.finance.models import LedgerEntry, Payment, Wallet

from . import services
from .models import (
    Appointment,
    AppointmentSlot,
    PatientProfile,
    PsychometricResponse,
    TherapistAvailability,
    TherapistProfile,
    TherapistReview,
    TherapistSessionOffer,
)
from .permissions import IsPsyAdmin
from .serializers import (
    AdminTherapistReviewSerializer,
    AppointmentSerializer,
    LeaveReviewSerializer,
    PsychometricResponseSerializer,
    TherapistProfileSerializer,
)


def _parse_range(request):
    today = timezone.localdate()
    raw_from = request.query_params.get("from")
    raw_to = request.query_params.get("to")
    date_from = parse_date(raw_from) if raw_from else today - timedelta(days=30)
    date_to = parse_date(raw_to) if raw_to else today
    if date_from is None:
        date_from = today - timedelta(days=30)
    if date_to is None:
        date_to = today
    return date_from, date_to


def _paginate(qs, request, *, default_size=25):
    try:
        page = max(1, int(request.query_params.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = min(
            100, max(1, int(request.query_params.get("page_size", default_size)))
        )
    except (TypeError, ValueError):
        page_size = default_size
    total = qs.count()
    start = (page - 1) * page_size
    return page, page_size, total, qs[start : start + page_size]


def _patient_display_name(patient: PatientProfile) -> str:
    user = patient.user
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.username


class AdminOverviewView(APIView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def get(self, request):
        now = timezone.now()
        week_ago = now - timedelta(days=7)
        upcoming = Appointment.objects.filter(
            status=Appointment.Status.CONFIRMED, starts_at__gte=now
        ).count()
        canceled_week = Appointment.objects.filter(
            status__in=[
                Appointment.Status.CANCELED_BY_ADMIN,
                Appointment.Status.CANCELED_BY_PATIENT,
                Appointment.Status.CANCELED_BY_THERAPIST,
            ],
            canceled_at__gte=week_ago,
        ).count()
        patients_count = PatientProfile.objects.count()
        therapists_active = TherapistProfile.objects.filter(is_active=True).count()
        pending_reviews = TherapistReview.objects.filter(
            text_status=TherapistReview.TextStatus.PENDING
        ).count()

        ledger_week = LedgerEntry.objects.filter(created_at__gte=week_ago)
        capture = ledger_week.filter(
            entry_type=LedgerEntry.EntryType.APPOINTMENT_CAPTURE
        ).aggregate(total=Coalesce(Sum("amount"), Decimal("0")))["total"]
        refund = ledger_week.filter(
            entry_type=LedgerEntry.EntryType.REFUND
        ).aggregate(total=Coalesce(Sum("amount"), Decimal("0")))["total"]

        recent = (
            Appointment.objects.select_related(
                "patient__user", "therapist", "session_type"
            )
            .order_by("-starts_at")[:8]
        )
        return Response(
            {
                "upcoming_confirmed_count": upcoming,
                "canceled_this_week": canceled_week,
                "patients_count": patients_count,
                "therapists_active_count": therapists_active,
                "pending_reviews_count": pending_reviews,
                "revenue_7d": str(capture - refund),
                "capture_7d": str(capture),
                "refund_7d": str(refund),
                "recent_appointments": AppointmentSerializer(recent, many=True).data,
            }
        )


class AdminPatientListView(APIView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        qs = PatientProfile.objects.select_related("user").order_by("user__username")
        if q:
            qs = qs.filter(
                Q(user__username__icontains=q)
                | Q(user__first_name__icontains=q)
                | Q(user__last_name__icontains=q)
                | Q(phone__icontains=q)
                | Q(national_id__icontains=q)
                | Q(user__email__icontains=q)
            )

        page, page_size, total, items = _paginate(qs, request)
        results = []
        for patient in items:
            appts = Appointment.objects.filter(patient=patient).order_by("-starts_at")
            last = appts.first()
            wallet = Wallet.objects.filter(user=patient.user).first()
            results.append(
                {
                    "id": patient.id,
                    "username": patient.user.username,
                    "display_name": _patient_display_name(patient),
                    "email": patient.user.email,
                    "phone": patient.phone,
                    "national_id": patient.national_id,
                    "appointments_count": appts.count(),
                    "last_appointment_at": last.starts_at if last else None,
                    "last_appointment_status": last.status if last else None,
                    "wallet_balance": str(wallet.balance) if wallet else "0",
                }
            )
        return Response(
            {
                "count": total,
                "page": page,
                "page_size": page_size,
                "results": results,
            }
        )


class AdminPatientDetailView(APIView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def get(self, request, pk):
        patient = get_object_or_404(
            PatientProfile.objects.select_related("user"), pk=pk
        )
        appts = (
            Appointment.objects.filter(patient=patient)
            .select_related("patient__user", "therapist", "session_type")
            .order_by("-starts_at")
        )
        last = appts.first()
        wallet = Wallet.objects.filter(user=patient.user).first()
        recent_appts = appts[:10]
        recent_responses = (
            PsychometricResponse.objects.filter(patient=patient)
            .select_related("form", "patient", "patient__user", "routed_therapist")
            .order_by("-submitted_at")[:10]
        )
        return Response(
            {
                "id": patient.id,
                "username": patient.user.username,
                "display_name": _patient_display_name(patient),
                "email": patient.user.email,
                "first_name": patient.user.first_name,
                "last_name": patient.user.last_name,
                "phone": patient.phone,
                "national_id": patient.national_id,
                "birth_date": patient.birth_date,
                "appointments_count": appts.count(),
                "last_appointment_at": last.starts_at if last else None,
                "last_appointment_status": last.status if last else None,
                "wallet_balance": str(wallet.balance) if wallet else "0",
                "recent_appointments": AppointmentSerializer(
                    recent_appts, many=True
                ).data,
                "recent_responses": PsychometricResponseSerializer(
                    recent_responses, many=True
                ).data,
            }
        )


class AdminTherapistListView(APIView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        qs = TherapistProfile.objects.select_related("user").order_by("display_name")
        is_active = request.query_params.get("is_active")
        is_accepting = request.query_params.get("is_accepting_patients")
        if is_active in ("true", "false"):
            qs = qs.filter(is_active=is_active == "true")
        if is_accepting in ("true", "false"):
            qs = qs.filter(is_accepting_patients=is_accepting == "true")
        if q:
            qs = qs.filter(
                Q(display_name__icontains=q)
                | Q(user__username__icontains=q)
                | Q(user__email__icontains=q)
            )

        page, page_size, total, items = _paginate(qs, request)
        results = []
        now = timezone.now()
        for therapist in items:
            appt_count = Appointment.objects.filter(therapist=therapist).count()
            open_slots = AppointmentSlot.objects.filter(
                therapist=therapist,
                status=AppointmentSlot.Status.OPEN,
                starts_at__gte=now,
                starts_at__lte=now + timedelta(days=14),
            ).count()
            results.append(
                {
                    **TherapistProfileSerializer(therapist).data,
                    "username": therapist.user.username,
                    "email": therapist.user.email,
                    "appointments_count": appt_count,
                    "open_slots_14d": open_slots,
                }
            )
        return Response(
            {
                "count": total,
                "page": page,
                "page_size": page_size,
                "results": results,
            }
        )


class AdminTherapistDetailView(APIView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def get(self, request, pk):
        therapist = get_object_or_404(
            TherapistProfile.objects.select_related("user"), pk=pk
        )
        now = timezone.now()
        offers = TherapistSessionOffer.objects.filter(
            therapist=therapist
        ).select_related("session_type")
        availability_count = TherapistAvailability.objects.filter(
            therapist=therapist, is_active=True
        ).count()
        open_slots = AppointmentSlot.objects.filter(
            therapist=therapist,
            status=AppointmentSlot.Status.OPEN,
            starts_at__gte=now,
            starts_at__lte=now + timedelta(days=14),
        ).count()
        recent = (
            Appointment.objects.filter(therapist=therapist)
            .select_related("patient__user", "therapist", "session_type")
            .order_by("-starts_at")[:15]
        )
        return Response(
            {
                **TherapistProfileSerializer(therapist).data,
                "username": therapist.user.username,
                "email": therapist.user.email,
                "availability_count": availability_count,
                "open_slots_14d": open_slots,
                "offers": [
                    {
                        "id": o.id,
                        "session_type_id": o.session_type_id,
                        "session_type_name": o.session_type.name,
                        "is_active": o.is_active,
                    }
                    for o in offers
                ],
                "recent_appointments": AppointmentSerializer(recent, many=True).data,
            }
        )


class AdminFinanceSummaryView(APIView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def get(self, request):
        date_from, date_to = _parse_range(request)
        ledger = LedgerEntry.objects.filter(
            created_at__date__gte=date_from,
            created_at__date__lte=date_to,
        )
        sep = Payment.objects.filter(
            status=Payment.Status.SUCCEEDED,
            provider=Payment.Provider.SEP,
            created_at__date__gte=date_from,
            created_at__date__lte=date_to,
        )
        capture = ledger.filter(
            entry_type=LedgerEntry.EntryType.APPOINTMENT_CAPTURE
        ).aggregate(total=Coalesce(Sum("amount"), Decimal("0")), n=Count("id"))
        refund = ledger.filter(entry_type=LedgerEntry.EntryType.REFUND).aggregate(
            total=Coalesce(Sum("amount"), Decimal("0")), n=Count("id")
        )
        sep_agg = sep.aggregate(
            total=Coalesce(Sum("amount"), Decimal("0")), n=Count("id")
        )
        return Response(
            {
                "from": str(date_from),
                "to": str(date_to),
                "sep_succeeded_total": str(sep_agg["total"]),
                "sep_succeeded_count": sep_agg["n"],
                "appointment_capture_total": str(capture["total"]),
                "appointment_capture_count": capture["n"],
                "refund_total": str(refund["total"]),
                "refund_count": refund["n"],
                "net_appointment_revenue": str(capture["total"] - refund["total"]),
            }
        )


class AdminFinanceLedgerView(APIView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def get(self, request):
        qs = LedgerEntry.objects.select_related("wallet__user").order_by("-created_at")
        entry_type = request.query_params.get("entry_type")
        username = request.query_params.get("user")
        date_from = request.query_params.get("from")
        date_to = request.query_params.get("to")
        if entry_type:
            qs = qs.filter(entry_type=entry_type)
        if username:
            qs = qs.filter(wallet__user__username__icontains=username)
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        page, page_size, total, items = _paginate(qs, request)
        results = [
            {
                "id": e.id,
                "username": e.wallet.user.username,
                "wallet_id": e.wallet_id,
                "direction": e.direction,
                "amount": str(e.amount),
                "balance_after": str(e.balance_after),
                "entry_type": e.entry_type,
                "reference": e.reference,
                "description": e.description,
                "created_at": e.created_at,
            }
            for e in items
        ]
        return Response(
            {
                "count": total,
                "page": page,
                "page_size": page_size,
                "results": results,
            }
        )


class AdminFinancePaymentsView(APIView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def get(self, request):
        qs = Payment.objects.select_related("user").order_by("-created_at")
        status_param = request.query_params.get("status")
        provider = request.query_params.get("provider")
        date_from = request.query_params.get("from")
        date_to = request.query_params.get("to")
        if status_param:
            qs = qs.filter(status=status_param)
        if provider:
            qs = qs.filter(provider=provider)
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        page, page_size, total, items = _paginate(qs, request)
        results = [
            {
                "id": p.id,
                "username": p.user.username,
                "amount": str(p.amount),
                "status": p.status,
                "provider": p.provider,
                "provider_ref": p.provider_ref,
                "purpose": p.purpose,
                "created_at": p.created_at,
            }
            for p in items
        ]
        return Response(
            {
                "count": total,
                "page": page,
                "page_size": page_size,
                "results": results,
            }
        )


class AdminFinanceAppointmentRevenueView(APIView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def get(self, request):
        qs = (
            LedgerEntry.objects.filter(
                entry_type__in=[
                    LedgerEntry.EntryType.APPOINTMENT_CAPTURE,
                    LedgerEntry.EntryType.REFUND,
                ]
            )
            .select_related("wallet__user")
            .order_by("-created_at")
        )
        date_from = request.query_params.get("from")
        date_to = request.query_params.get("to")
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        entry_type = request.query_params.get("entry_type")
        if entry_type:
            qs = qs.filter(entry_type=entry_type)

        page, page_size, total, items = _paginate(qs, request)
        results = []
        for e in items:
            appt_id = None
            if e.reference.startswith("psy.appointment:"):
                try:
                    appt_id = int(e.reference.split(":", 1)[1])
                except (IndexError, ValueError):
                    appt_id = None
            results.append(
                {
                    "id": e.id,
                    "username": e.wallet.user.username,
                    "entry_type": e.entry_type,
                    "direction": e.direction,
                    "amount": str(e.amount),
                    "reference": e.reference,
                    "appointment_id": appt_id,
                    "created_at": e.created_at,
                }
            )
        return Response(
            {
                "count": total,
                "page": page,
                "page_size": page_size,
                "results": results,
            }
        )


class AdminReviewListView(APIView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def get(self, request):
        qs = TherapistReview.objects.select_related(
            "patient__user", "therapist", "appointment"
        ).order_by("-created_at")
        status_param = request.query_params.get("status")
        therapist = request.query_params.get("therapist")
        if status_param:
            qs = qs.filter(text_status=status_param)
        if therapist:
            qs = qs.filter(therapist_id=therapist)
        return Response(AdminTherapistReviewSerializer(qs[:200], many=True).data)


class AdminReviewApproveView(APIView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def post(self, request, pk: int):
        review = get_object_or_404(TherapistReview, pk=pk)
        ser = LeaveReviewSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            review = services.approve_review(
                review=review,
                reviewer=request.user,
                admin_note=ser.validated_data.get("admin_note", ""),
            )
        except services.ReviewError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(AdminTherapistReviewSerializer(review).data)


class AdminReviewRejectView(APIView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def post(self, request, pk: int):
        review = get_object_or_404(TherapistReview, pk=pk)
        ser = LeaveReviewSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            review = services.reject_review(
                review=review,
                reviewer=request.user,
                admin_note=ser.validated_data.get("admin_note", ""),
            )
        except services.ReviewError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(AdminTherapistReviewSerializer(review).data)
