from django.conf import settings
from django.shortcuts import redirect
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import services
from .models import LedgerEntry, Payment, WithdrawalRequest
from .serializers import (
    ConfirmPaymentSerializer,
    CreateWithdrawalSerializer,
    LedgerEntrySerializer,
    PaymentSerializer,
    RejectWithdrawalSerializer,
    VandarInitiateSerializer,
    WalletSerializer,
    WithdrawalSerializer,
)


class IsPlatformFinance(BasePermission):
    """Platform ledger authority. Generic is_staff is not enough."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.has_perm("finance.manage_platform_finance"))


class FinanceSummaryView(APIView):
    """Institute admins see their host. Platform finance sees every institute."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from datetime import timedelta

        from django.utils import timezone
        from django.utils.dateparse import parse_date

        from apps.kernel.tenancy.hosts import describe_host
        from apps.kernel.tenancy.models import Institute
        from apps.kernel.tenancy.services import is_institute_admin

        from .reports import institute_summary, platform_summary

        today = timezone.localdate()
        date_from = parse_date(request.query_params.get("from") or "") or today - timedelta(days=30)
        date_to = parse_date(request.query_params.get("to") or "") or today
        binding = getattr(request, "tenancy_host", None) or describe_host(request.get_host())
        if binding.kind == "institute" and binding.slug:
            institute = Institute.objects.filter(slug=binding.slug, is_active=True).first()
            if institute is None or not (
                is_institute_admin(request.user, institute.slug)
                or IsPlatformFinance().has_permission(request, self)
            ):
                return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)
            return Response(institute_summary(institute, date_from, date_to))
        if not IsPlatformFinance().has_permission(request, self):
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)
        return Response(platform_summary(date_from, date_to))


class WalletView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        wallet = services.get_or_create_wallet(request.user)
        return Response(WalletSerializer(wallet).data)


class LedgerListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        wallet = services.get_or_create_wallet(request.user)
        qs = LedgerEntry.objects.filter(wallet=wallet)

        try:
            page = max(1, int(request.query_params.get("page", 1)))
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
        except (TypeError, ValueError):
            page_size = 20

        total = qs.count()
        start = (page - 1) * page_size
        end = start + page_size
        items = qs[start:end]
        return Response(
            {
                "count": total,
                "page": page,
                "page_size": page_size,
                "results": LedgerEntrySerializer(items, many=True).data,
            }
        )


class PaymentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentSerializer
    lookup_field = "public_id"
    lookup_value_regex = "[0-9a-fA-F-]{32,36}"

    def get_queryset(self):
        qs = Payment.objects.filter(user=self.request.user)
        if IsPlatformFinance().has_permission(self.request, self):
            qs = Payment.objects.all()
        return qs.order_by("-created_at")

    @action(detail=True, methods=["post"], permission_classes=[IsPlatformFinance])
    def confirm(self, request, public_id=None):
        payment = self.get_object()
        if payment.provider != Payment.Provider.MANUAL:
            return Response(
                {"detail": "Only a manual payment can be confirmed here."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ser = ConfirmPaymentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            payment = services.confirm_payment(
                payment=payment,
                provider_ref=ser.validated_data.get("provider_ref", ""),
                metadata=ser.validated_data.get("metadata"),
            )
        except services.FinanceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PaymentSerializer(payment).data)


class WithdrawalViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = WithdrawalSerializer

    def get_queryset(self):
        if IsPlatformFinance().has_permission(self.request, self):
            return WithdrawalRequest.objects.select_related("wallet").all()
        wallet = services.get_or_create_wallet(self.request.user)
        return WithdrawalRequest.objects.filter(wallet=wallet)

    def create(self, request, *args, **kwargs):
        ser = CreateWithdrawalSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            withdrawal = services.create_withdrawal(
                user=request.user,
                amount=ser.validated_data["amount"],
                bank_details=ser.validated_data["bank_details"],
                ticket_reference=ser.validated_data.get("ticket_reference", ""),
                idempotency_key=ser.validated_data["idempotency_key"],
            )
        except services.InsufficientFunds as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except services.FinanceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(WithdrawalSerializer(withdrawal).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], permission_classes=[IsPlatformFinance])
    def approve(self, request, pk=None):
        withdrawal = self.get_object()
        try:
            withdrawal = services.approve_withdrawal(
                withdrawal=withdrawal, processed_by=request.user
            )
        except services.FinanceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(WithdrawalSerializer(withdrawal).data)

    @action(detail=True, methods=["post"], permission_classes=[IsPlatformFinance])
    def paid(self, request, pk=None):
        withdrawal = self.get_object()
        try:
            withdrawal = services.mark_withdrawal_paid(
                withdrawal=withdrawal, processed_by=request.user
            )
        except services.FinanceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(WithdrawalSerializer(withdrawal).data)

    @action(detail=True, methods=["post"], permission_classes=[IsPlatformFinance])
    def reject(self, request, pk=None):
        withdrawal = self.get_object()
        ser = RejectWithdrawalSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            withdrawal = services.reject_withdrawal(
                withdrawal=withdrawal,
                processed_by=request.user,
                reason=ser.validated_data.get("reason", ""),
            )
        except services.FinanceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(WithdrawalSerializer(withdrawal).data)


class VandarInitiateView(APIView):
    """Authenticated wallet top-up. Checkout goes through each module."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = VandarInitiateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        institute = _institute_from_request(request)
        return_path = "/patient/wallet" if institute is not None else "/payment/result"
        try:
            result = services.start_topup(
                user=request.user,
                amount=ser.validated_data["amount"],
                purpose=ser.validated_data.get("purpose") or "wallet.topup",
                institute=institute,
                return_path=return_path,
                request_host=request.get_host(),
            )
        except services.FinanceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "payment": PaymentSerializer(result["payment"]).data,
                "redirect_url": result["redirect_url"],
                "provider_ref": result["provider_ref"],
                "sandbox": result["sandbox"],
            },
            status=status.HTTP_201_CREATED,
        )


class VandarCallbackView(APIView):
    """Public Vandar return URL. Redirects the browser and reveals no error detail."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "vandar_callback"

    def get(self, request):
        return self._handle(request.query_params.dict())

    def post(self, request):
        data = {}
        if hasattr(request.data, "dict"):
            data = request.data.dict()
        elif isinstance(request.data, dict):
            data = dict(request.data)
        data = {**request.query_params.dict(), **data}
        return self._handle(data)

    def _handle(self, data: dict):
        try:
            payment = services.handle_vandar_callback(data=data)
        except services.FinanceError:
            return redirect(_unknown_token_return())
        return redirect(build_return_url(payment, _return_status(payment)))


def _return_status(payment: Payment) -> str:
    if payment.status == Payment.Status.SUCCEEDED:
        return "success"
    if payment.status in (Payment.Status.FAILED, Payment.Status.CANCELED):
        return "failed"
    return "pending"


def _platform_origin() -> str:
    return (getattr(settings, "PLATFORM_FRONTEND_ORIGIN", "") or "").rstrip("/")


def _unknown_token_return() -> str:
    origin = _platform_origin()
    if not origin:
        return "/payment/result?status=failed"
    return f"{origin}/payment/result?status=failed"


def build_return_url(payment: Payment, status: str) -> str:
    """https://host[/i/slug]/path?payment_id=<public_id>&status=..."""
    from apps.kernel.tenancy.models import Institute, InstituteDomain

    host = (payment.return_host or "").lower()
    path = payment.return_path or "/payment/result"
    if not path.startswith("/"):
        path = f"/{path}"
    query = f"payment_id={payment.public_id}&status={status}"
    if host:
        prefix = ""
        if payment.institute_id:
            owns = InstituteDomain.objects.filter(
                institute_id=payment.institute_id,
                hostname=host,
                is_active=True,
            ).exists()
            if not owns:
                prefix = f"/i/{payment.institute.slug}"
        return f"https://{host}{prefix}{path}?{query}"

    origin = _platform_origin()
    if payment.institute_id:
        institute = payment.institute
        canonical = (
            InstituteDomain.objects.filter(
                institute_id=institute.id,
                is_active=True,
                is_canonical=True,
            )
            .order_by("id")
            .first()
        )
        if canonical is not None:
            return f"https://{canonical.hostname}{path}?{query}"
        # Only a real origin may carry /i/<slug>. An empty
        # PLATFORM_FRONTEND_ORIGIN must not become a hostless redirect.
        if origin and institute.frontend_mode == Institute.FrontendMode.STANDARD:
            return f"{origin}/i/{institute.slug}{path}?{query}"
    if origin:
        return f"{origin}{path}?{query}"
    return f"{path}?{query}"


def _institute_from_request(request):
    from apps.kernel.tenancy.hosts import describe_host
    from apps.kernel.tenancy.models import Institute

    binding = getattr(request, "tenancy_host", None) or describe_host(request.get_host())
    if binding.kind != "institute" or not binding.slug:
        return None
    return Institute.objects.filter(slug=binding.slug, is_active=True).first()
