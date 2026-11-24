"""Tenant-scoped booking HTTP API. Payloads use provider, customer, and service_type.

The therapist, patient, and session_type keys are compatibility aliases so the
current psychology portals can keep calling these routes.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.kernel.tenancy.scoping import InstituteScopedMixin
from apps.kernel.tenancy.services import user_has_role

from .models import (
    Appointment,
    AvailabilityException,
    LeaveRequest,
    Provider,
    ProviderAvailability,
    ProviderServiceOffer,
    ServiceType,
    Slot,
)
from .permissions import IsBookingAdmin, IsCustomer, IsProvider
from .serializers import (
    AvailabilitySerializer,
    BookAppointmentSerializer,
    CancelSerializer,
    ConfirmSerializer,
    ExceptionSerializer,
    LeaveSerializer,
    MeetingLinkSerializer,
    MoveSerializer,
    OfferSerializer,
    ProviderSerializer,
    RegenerateSerializer,
    ReviewSubmitSerializer,
    ServiceTypeSerializer,
    SlotWriteSerializer,
)
from .services import (
    BookingError,
    LeaveError,
    ReviewError,
    SlotError,
    admin_book_appointment,
    approve_leave_request,
    book_slot,
    cancel_appointment,
    cancel_leave_request,
    complete_appointment,
    confirm_appointment_payment,
    create_open_slot,
    delete_open_slot,
    move_appointment,
    regenerate_slots_for_provider,
    reject_leave_request,
    submit_appointment_review,
    submit_leave_request,
)
from apps.modules.reviews.models import Review
from apps.modules.reviews.services import reviews_for_target

User = get_user_model()
SCHEDULE_DISABLED = "Provider schedule is managed by the institute admin."


def _detail(message, status=400):
    return Response({"detail": str(message)}, status=status)


def _provider(institute, raw_id):
    """Provider id, or the psychology therapist-profile id used by older clients."""
    found = Provider.objects.filter(institute=institute, pk=raw_id).first()
    if found:
        return found
    return Provider.objects.filter(institute=institute, therapist_profile__pk=raw_id).first()


def _customer_name(user) -> str:
    return user.get_full_name() or user.username


def _service_payload(service):
    if service is None:
        return None
    return ServiceTypeSerializer(service).data


def _slot_payload(slot):
    profile = getattr(slot.provider, "therapist_profile", None)
    return {
        "id": slot.id,
        "provider": slot.provider_id,
        "provider_name": slot.provider.display_name,
        "therapist": {
            "id": profile.id if profile else slot.provider_id,
            "display_name": slot.provider.display_name,
            "bio": getattr(profile, "bio", "") or "",
            "specialties": getattr(profile, "specialties", []) or [],
            "is_accepting_patients": slot.provider.is_accepting,
            "is_active": slot.provider.is_active,
        },
        "service_type": _service_payload(slot.service_type),
        "session_type": _service_payload(slot.service_type),
        "starts_at": slot.starts_at,
        "ends_at": slot.ends_at,
        "status": slot.status,
        "hold_expires_at": slot.hold_expires_at,
    }


def _appointment_payload(appointment):
    profile = getattr(appointment.provider, "therapist_profile", None)
    patient = getattr(appointment.customer, "patient_profile", None)
    name = _customer_name(appointment.customer)
    return {
        "id": appointment.id,
        "slot": appointment.slot_id,
        "provider": appointment.provider_id,
        "provider_name": appointment.provider.display_name,
        "customer": appointment.customer_id,
        "customer_name": name,
        "service_type": appointment.service_type_id,
        "service_type_name": appointment.service_type.name,
        "service_type_modality": appointment.service_type.modality,
        "therapist": profile.id if profile else appointment.provider_id,
        "therapist_name": appointment.provider.display_name,
        "patient": patient.id if patient else appointment.customer_id,
        "patient_name": name,
        "session_type": appointment.service_type_id,
        "session_type_name": appointment.service_type.name,
        "session_type_modality": appointment.service_type.modality,
        "starts_at": appointment.starts_at,
        "ends_at": appointment.ends_at,
        "status": appointment.status,
        "price_snapshot": appointment.price_snapshot,
        "payment_ref": appointment.payment_ref,
        "canceled_at": appointment.canceled_at,
        "cancellation_reason": appointment.cancellation_reason,
        "refund_policy_applied": appointment.refund_policy_applied,
        "meeting_link": appointment.meeting_link,
        "created_at": appointment.created_at,
    }


def _review_payload(review, *, hide_pending_text: bool):
    body = review.body
    if hide_pending_text and review.text_status != Review.TextStatus.APPROVED:
        body = ""
    return {
        "id": review.id,
        "rating": review.rating,
        "body": body,
        "text_status": review.text_status,
        "author_name": _customer_name(review.author),
        "created_at": review.created_at,
    }


class ServiceTypeListView(InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [AllowAny]

    def get(self, request, institute_slug=None):
        qs = ServiceType.objects.filter(institute=self.institute)
        if not user_has_role(request.user, self.institute.slug, "admin"):
            qs = qs.filter(is_active=True)
        return Response(ServiceTypeSerializer(qs, many=True).data)

    def post(self, request, institute_slug=None):
        if not IsBookingAdmin().has_permission(request, self):
            return _detail("Admin only.", 403)
        ser = ServiceTypeSerializer(data=request.data, context={"institute": self.institute})
        ser.is_valid(raise_exception=True)
        ser.save(institute=self.institute)
        return Response(ser.data, status=201)


class ServiceTypeDetailView(InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [AllowAny]

    def get(self, request, slug, institute_slug=None):
        obj = get_object_or_404(ServiceType, institute=self.institute, slug=slug)
        return Response(ServiceTypeSerializer(obj).data)

    def patch(self, request, slug, institute_slug=None):
        if not IsBookingAdmin().has_permission(request, self):
            return _detail("Admin only.", 403)
        obj = get_object_or_404(ServiceType, institute=self.institute, slug=slug)
        ser = ServiceTypeSerializer(obj, data=request.data, partial=True, context={"institute": self.institute})
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)

    def delete(self, request, slug, institute_slug=None):
        if not IsBookingAdmin().has_permission(request, self):
            return _detail("Admin only.", 403)
        get_object_or_404(ServiceType, institute=self.institute, slug=slug).delete()
        return Response(status=204)


class ProviderListView(InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [AllowAny]

    def get(self, request, institute_slug=None):
        qs = (
            Provider.objects.filter(institute=self.institute, is_active=True, is_accepting=True)
            .annotate(
                rating_avg=Avg("shared_reviews__rating"),
                rating_count=Count("shared_reviews", distinct=True),
            )
            .order_by("display_name")
        )
        return Response(ProviderSerializer(qs, many=True).data)


class ProviderDetailView(InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [AllowAny]

    def get(self, request, pk, institute_slug=None):
        provider = _provider(self.institute, pk)
        if provider is None or not provider.is_active:
            return _detail("Provider not found.", 404)
        return Response(ProviderSerializer(provider).data)


class ProviderSlotListView(InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [AllowAny]

    def get(self, request, pk, institute_slug=None):
        provider = _provider(self.institute, pk)
        if provider is None:
            return _detail("Provider not found.", 404)
        qs = Slot.objects.filter(
            provider=provider,
            status=Slot.Status.OPEN,
            appointment__isnull=True,
            starts_at__gte=timezone.now(),
        ).select_related("provider", "service_type", "provider__therapist_profile")
        if request.query_params.get("from"):
            qs = qs.filter(starts_at__date__gte=request.query_params["from"])
        if request.query_params.get("to"):
            qs = qs.filter(starts_at__date__lte=request.query_params["to"])
        return Response([_slot_payload(slot) for slot in qs[:200]])


class ProviderReviewListView(InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [AllowAny]

    def get(self, request, pk, institute_slug=None):
        provider = _provider(self.institute, pk)
        if provider is None:
            return _detail("Provider not found.", 404)
        qs = (
            reviews_for_target(self.institute, provider)
            .filter(text_status=Review.TextStatus.APPROVED)
            .exclude(body="")
            .select_related("author")
            .order_by("-created_at")[:100]
        )
        return Response([_review_payload(item, hide_pending_text=False) for item in qs])


class MyReviewListView(InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [IsAuthenticated, IsProvider]

    def get(self, request, institute_slug=None):
        provider = get_object_or_404(Provider, institute=self.institute, user=request.user)
        qs = reviews_for_target(self.institute, provider).select_related("author").order_by("-created_at")[:200]
        return Response([_review_payload(item, hide_pending_text=True) for item in qs])


class _ScheduleDisabled(InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [IsAuthenticated, IsProvider]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied(SCHEDULE_DISABLED)


class SlotListCreateView(InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [IsAuthenticated, IsBookingAdmin]

    def get(self, request, institute_slug=None):
        qs = Slot.objects.filter(institute=self.institute).select_related("provider", "service_type")
        if request.query_params.get("provider"):
            provider = _provider(self.institute, request.query_params["provider"])
            qs = qs.filter(provider=provider) if provider else qs.none()
        if request.query_params.get("from"):
            qs = qs.filter(starts_at__date__gte=request.query_params["from"])
        if request.query_params.get("to"):
            qs = qs.filter(starts_at__date__lte=request.query_params["to"])
        return Response([_slot_payload(slot) for slot in qs[:200]])

    def post(self, request, institute_slug=None):
        ser = SlotWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        provider = _provider(self.institute, ser.validated_data["provider_id"])
        if provider is None:
            return _detail("Provider not found.", 404)
        try:
            slot = create_open_slot(
                provider=provider,
                starts_at=ser.validated_data["starts_at"],
                ends_at=ser.validated_data["ends_at"],
            )
        except SlotError as exc:
            return _detail(exc)
        return Response(_slot_payload(slot), status=201)


class SlotDetailView(InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [IsAuthenticated, IsBookingAdmin]

    def delete(self, request, pk, institute_slug=None):
        slot = get_object_or_404(Slot, pk=pk, institute=self.institute)
        try:
            delete_open_slot(slot=slot)
        except SlotError as exc:
            return _detail(exc)
        return Response(status=204)


class RegenerateSlotsView(InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [IsAuthenticated, IsBookingAdmin]

    def post(self, request, institute_slug=None):
        ser = RegenerateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        provider = _provider(self.institute, ser.validated_data["provider_id"])
        if provider is None:
            return _detail("Provider not found.", 404)
        created = regenerate_slots_for_provider(
            provider=provider,
            range_start=ser.validated_data["range_start"],
            range_end=ser.validated_data["range_end"],
        )
        return Response({"created": created})


class _ProviderChild:
    def _provider(self, request, pk):
        provider = _provider(self.institute, pk)
        if provider is None:
            return None
        return provider


class AvailabilityListView(_ProviderChild, InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [IsAuthenticated, IsBookingAdmin]

    def get(self, request, pk, institute_slug=None):
        provider = self._provider(request, pk)
        if provider is None:
            return _detail("Provider not found.", 404)
        rows = ProviderAvailability.objects.filter(provider=provider)
        return Response(AvailabilitySerializer(rows, many=True).data)

    def post(self, request, pk, institute_slug=None):
        provider = self._provider(request, pk)
        if provider is None:
            return _detail("Provider not found.", 404)
        ser = AvailabilitySerializer(data=request.data, context={"provider": provider})
        ser.is_valid(raise_exception=True)
        ser.save(provider=provider, institute=self.institute)
        return Response(ser.data, status=201)


class AvailabilityDetailView(InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [IsAuthenticated, IsBookingAdmin]

    def _row(self, pk, availability_id):
        provider = _provider(self.institute, pk)
        if provider is None:
            return None
        return ProviderAvailability.objects.filter(
            pk=availability_id, provider=provider, institute=self.institute
        ).first()

    def patch(self, request, pk, availability_id, institute_slug=None):
        obj = self._row(pk, availability_id)
        if obj is None:
            return _detail("Provider not found.", 404)
        ser = AvailabilitySerializer(obj, data=request.data, partial=True, context={"provider": obj.provider})
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)

    def delete(self, request, pk, availability_id, institute_slug=None):
        obj = self._row(pk, availability_id)
        if obj is None:
            return _detail("Provider not found.", 404)
        obj.delete()
        return Response(status=204)


class OfferListView(_ProviderChild, InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [IsAuthenticated, IsBookingAdmin]

    def get(self, request, pk, institute_slug=None):
        provider = self._provider(request, pk)
        if provider is None:
            return _detail("Provider not found.", 404)
        rows = ProviderServiceOffer.objects.filter(provider=provider).select_related("service_type")
        return Response(OfferSerializer(rows, many=True).data)

    def post(self, request, pk, institute_slug=None):
        provider = self._provider(request, pk)
        if provider is None:
            return _detail("Provider not found.", 404)
        ser = OfferSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if ser.validated_data["service_type"].institute_id != self.institute.id:
            return _detail("Service type not found.", 404)
        offer, _created = ProviderServiceOffer.objects.update_or_create(
            provider=provider,
            service_type=ser.validated_data["service_type"],
            defaults={"is_active": ser.validated_data.get("is_active", True), "institute": self.institute},
        )
        return Response(OfferSerializer(offer).data, status=201)


class OfferDetailView(InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [IsAuthenticated, IsBookingAdmin]

    def _offer(self, pk, offer_id):
        provider = _provider(self.institute, pk)
        if provider is None:
            return None
        return (
            ProviderServiceOffer.objects.filter(pk=offer_id, provider=provider, institute=self.institute)
            .select_related("service_type")
            .first()
        )

    def patch(self, request, pk, offer_id, institute_slug=None):
        offer = self._offer(pk, offer_id)
        if offer is None:
            return _detail("Offer not found.", 404)
        ser = OfferSerializer(offer, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        service = ser.validated_data.get("service_type")
        if service is not None and service.institute_id != self.institute.id:
            return _detail("Service type not found.", 404)
        ser.save()
        return Response(OfferSerializer(ser.instance).data)

    def delete(self, request, pk, offer_id, institute_slug=None):
        offer = self._offer(pk, offer_id)
        if offer is None:
            return _detail("Offer not found.", 404)
        offer.delete()
        return Response(status=204)


class ExceptionListView(_ProviderChild, InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [IsAuthenticated, IsBookingAdmin]

    def get(self, request, pk, institute_slug=None):
        provider = self._provider(request, pk)
        if provider is None:
            return _detail("Provider not found.", 404)
        rows = AvailabilityException.objects.filter(provider=provider)
        return Response(ExceptionSerializer(rows, many=True).data)

    def post(self, request, pk, institute_slug=None):
        provider = self._provider(request, pk)
        if provider is None:
            return _detail("Provider not found.", 404)
        ser = ExceptionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save(provider=provider, institute=self.institute)
        return Response(ser.data, status=201)


class ExceptionDetailView(InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [IsAuthenticated, IsBookingAdmin]

    def delete(self, request, pk, exception_id, institute_slug=None):
        provider = _provider(self.institute, pk)
        if provider is None:
            return _detail("Provider not found.", 404)
        row = AvailabilityException.objects.filter(
            pk=exception_id, provider=provider, institute=self.institute
        ).first()
        if row is None:
            return _detail("Exception not found.", 404)
        row.delete()
        return Response(status=204)


class LeaveListCreateView(InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [IsAuthenticated]

    def get(self, request, institute_slug=None):
        qs = LeaveRequest.objects.filter(institute=self.institute).select_related("provider")
        if IsBookingAdmin().has_permission(request, self):
            return Response(LeaveSerializer(qs[:200], many=True).data)
        if not IsProvider().has_permission(request, self):
            return _detail("Not allowed.", 403)
        provider = get_object_or_404(Provider, institute=self.institute, user=request.user)
        return Response(LeaveSerializer(qs.filter(provider=provider), many=True).data)

    def post(self, request, institute_slug=None):
        if not IsProvider().has_permission(request, self):
            return _detail("Not allowed.", 403)
        provider = get_object_or_404(Provider, institute=self.institute, user=request.user)
        ser = LeaveSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            leave = submit_leave_request(
                provider=provider,
                starts_on=data["starts_on"],
                ends_on=data["ends_on"],
                reason=data["reason"],
                start_time=data.get("start_time"),
                end_time=data.get("end_time"),
            )
        except LeaveError as exc:
            return _detail(exc)
        return Response(LeaveSerializer(leave).data, status=201)


class LeaveActionView(InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, action, institute_slug=None):
        leave = get_object_or_404(LeaveRequest, pk=pk, institute=self.institute)
        try:
            if action == "cancel":
                if leave.provider.user_id != request.user.id:
                    return _detail("Not allowed.", 403)
                leave = cancel_leave_request(leave=leave)
            elif action in {"approve", "reject"}:
                if not IsBookingAdmin().has_permission(request, self):
                    return _detail("Admin only.", 403)
                note = request.data.get("admin_note", "")
                if action == "approve":
                    leave, _created, _conflicts = approve_leave_request(
                        leave=leave, reviewer=request.user, admin_note=note
                    )
                else:
                    leave = reject_leave_request(leave=leave, reviewer=request.user, admin_note=note)
            else:
                return _detail("Unknown action.", 404)
        except LeaveError as exc:
            return _detail(exc)
        return Response(LeaveSerializer(leave).data)


def _appointments_for(request, institute):
    qs = Appointment.objects.filter(institute=institute).select_related(
        "customer", "provider", "service_type", "slot", "provider__therapist_profile", "customer__patient_profile"
    )
    user = request.user
    if user_has_role(user, institute.slug, "admin"):
        scoped = qs
    elif user_has_role(user, institute.slug, "staff") and Provider.objects.filter(institute=institute, user=user).exists():
        scoped = qs.filter(provider__user=user)
    elif user_has_role(user, institute.slug, "member"):
        scoped = qs.filter(customer=user)
    else:
        scoped = qs.none()
    provider_param = request.query_params.get("provider") or request.query_params.get("therapist")
    if provider_param and provider_param.isdigit():
        provider = _provider(institute, int(provider_param))
        scoped = scoped.filter(provider=provider) if provider else scoped.none()
    status_param = request.query_params.get("status")
    if status_param:
        scoped = scoped.filter(status=status_param)
    if request.query_params.get("from"):
        scoped = scoped.filter(starts_at__date__gte=request.query_params["from"])
    if request.query_params.get("to"):
        scoped = scoped.filter(starts_at__date__lte=request.query_params["to"])
    return scoped.order_by("-starts_at")


class AppointmentListCreateView(InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [IsAuthenticated]

    def get(self, request, institute_slug=None):
        qs = _appointments_for(request, self.institute)
        page_raw = request.query_params.get("page")
        if page_raw is None:
            return Response([_appointment_payload(item) for item in qs[:100]])
        try:
            page = max(1, int(page_raw))
            page_size = min(100, max(1, int(request.query_params.get("page_size", 25))))
        except (TypeError, ValueError):
            page, page_size = 1, 25
        total = qs.count()
        start = (page - 1) * page_size
        return Response(
            {
                "count": total,
                "page": page,
                "page_size": page_size,
                "results": [_appointment_payload(item) for item in qs[start : start + page_size]],
            }
        )

    def post(self, request, institute_slug=None):
        ser = BookAppointmentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        is_admin = IsBookingAdmin().has_permission(request, self)
        customer_id = ser.validated_data.get("customer_id")
        if customer_id and is_admin:
            customer = get_object_or_404(User, pk=customer_id)
        else:
            if not IsCustomer().has_permission(request, self) and not is_admin:
                return _detail("Membership required.", 403)
            customer = request.user
        payment = ser.validated_data.get("payment")
        try:
            if payment and is_admin:
                appointment = admin_book_appointment(
                    customer=customer,
                    slot_id=ser.validated_data["slot_id"],
                    service_type_id=ser.validated_data["service_type_id"],
                    payment=payment,
                )
            else:
                appointment = book_slot(
                    customer=customer,
                    slot_id=ser.validated_data["slot_id"],
                    service_type_id=ser.validated_data["service_type_id"],
                )
        except Slot.DoesNotExist:
            return _detail("Slot not found.", 404)
        except BookingError as exc:
            return _detail(exc)
        appointment = Appointment.objects.select_related(
            "customer", "provider", "service_type", "provider__therapist_profile", "customer__patient_profile"
        ).get(pk=appointment.pk)
        return Response(_appointment_payload(appointment), status=201)


class AppointmentDetailView(InstituteScopedMixin, APIView):
    required_module = "booking"
    permission_classes = [IsAuthenticated]

    def _get(self, request, pk):
        return get_object_or_404(_appointments_for(request, self.institute), pk=pk)

    def get(self, request, pk, institute_slug=None):
        return Response(_appointment_payload(self._get(request, pk)))

    def post(self, request, pk, action, institute_slug=None):
        appointment = self._get(request, pk)
        try:
            if action == "confirm_payment":
                owns = appointment.customer_id == request.user.id
                if not owns and not IsBookingAdmin().has_permission(request, self):
                    return _detail("Not allowed.", 403)
                ser = ConfirmSerializer(data=request.data)
                ser.is_valid(raise_exception=True)
                appointment = confirm_appointment_payment(
                    appointment=appointment,
                    payment_ref=ser.validated_data["payment_ref"],
                    idempotency_key=ser.validated_data["idempotency_key"],
                    allow_offline=IsBookingAdmin().has_permission(request, self),
                )
            elif action == "cancel":
                ser = CancelSerializer(data=request.data)
                ser.is_valid(raise_exception=True)
                if IsBookingAdmin().has_permission(request, self):
                    role = "admin"
                elif appointment.provider.user_id == request.user.id:
                    return _detail("Providers cannot cancel appointments. Submit a leave request.", 403)
                elif appointment.customer_id == request.user.id:
                    role = "patient"
                else:
                    return _detail("Not allowed.", 403)
                appointment = cancel_appointment(
                    appointment=appointment, canceled_by=role, reason=ser.validated_data.get("reason", "")
                )
            elif action == "complete":
                is_provider = appointment.provider.user_id == request.user.id
                if not (is_provider or IsBookingAdmin().has_permission(request, self)):
                    return _detail("Not allowed.", 403)
                appointment = complete_appointment(appointment=appointment)
            elif action == "move":
                if not IsBookingAdmin().has_permission(request, self):
                    return _detail("Admin only.", 403)
                ser = MoveSerializer(data=request.data)
                ser.is_valid(raise_exception=True)
                appointment = move_appointment(appointment=appointment, new_slot_id=ser.validated_data["new_slot_id"])
            elif action == "set_meeting_link":
                is_provider = appointment.provider.user_id == request.user.id
                if not (is_provider or IsBookingAdmin().has_permission(request, self)):
                    return _detail("Not allowed.", 403)
                ser = MeetingLinkSerializer(data=request.data)
                ser.is_valid(raise_exception=True)
                appointment.meeting_link = ser.validated_data.get("meeting_link", "") or ""
                appointment.save(update_fields=["meeting_link", "updated_at"])
            elif action == "review":
                if appointment.customer_id != request.user.id:
                    return _detail("Not allowed.", 403)
                ser = ReviewSubmitSerializer(data=request.data)
                ser.is_valid(raise_exception=True)
                review = submit_appointment_review(
                    appointment=appointment,
                    customer=request.user,
                    rating=ser.validated_data["rating"],
                    body=ser.validated_data.get("body", ""),
                )
                return Response(_review_payload(review, hide_pending_text=False), status=201)
            else:
                return _detail("Unknown action.", 404)
        except (BookingError, ReviewError, Slot.DoesNotExist) as exc:
            status = 404 if isinstance(exc, Slot.DoesNotExist) else 400
            return _detail(getattr(exc, "args", ["Slot not found."])[0] if not str(exc) else exc, status)
        except Exception as exc:
            return _detail(exc)
        appointment = Appointment.objects.select_related(
            "customer", "provider", "service_type", "provider__therapist_profile", "customer__patient_profile"
        ).get(pk=appointment.pk)
        return Response(_appointment_payload(appointment))
