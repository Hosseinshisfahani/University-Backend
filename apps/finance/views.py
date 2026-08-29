from django.conf import settings
from django.shortcuts import redirect
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import LedgerEntry, Payment, WithdrawalRequest
from .serializers import (
    ConfirmPaymentSerializer,
    CreatePaymentSerializer,
    CreateWithdrawalSerializer,
    LedgerEntrySerializer,
    PaymentSerializer,
    RejectWithdrawalSerializer,
    SepInitiateSerializer,
    WalletSerializer,
    WithdrawalSerializer,
)


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


class PaymentViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentSerializer

    def get_queryset(self):
        qs = Payment.objects.filter(user=self.request.user)
        if self.request.user.is_staff:
            qs = Payment.objects.all()
        return qs.order_by("-created_at")

    def create(self, request, *args, **kwargs):
        ser = CreatePaymentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        payment = services.create_payment(
            user=request.user,
            amount=ser.validated_data["amount"],
            purpose=ser.validated_data.get("purpose", ""),
            provider=ser.validated_data.get("provider", Payment.Provider.SEP),
            metadata=ser.validated_data.get("metadata"),
        )
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def confirm(self, request, pk=None):
        try:
            payment = Payment.objects.get(pk=pk)
        except Payment.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
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
        if self.request.user.is_staff:
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

    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def approve(self, request, pk=None):
        withdrawal = self.get_object()
        try:
            withdrawal = services.approve_withdrawal(
                withdrawal=withdrawal, processed_by=request.user
            )
        except services.FinanceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(WithdrawalSerializer(withdrawal).data)

    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def paid(self, request, pk=None):
        withdrawal = self.get_object()
        try:
            withdrawal = services.mark_withdrawal_paid(
                withdrawal=withdrawal, processed_by=request.user
            )
        except services.FinanceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(WithdrawalSerializer(withdrawal).data)

    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
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


class SepInitiateView(APIView):
    """Authenticated: create pending SEP payment and return bank redirect URL."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = SepInitiateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            result = services.initiate_sep_payment(
                user=request.user,
                amount=ser.validated_data["amount"],
                purpose=ser.validated_data.get("purpose", ""),
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


class SepCallbackView(APIView):
    """
    Public bank return URL. CSRF-exempt via empty authentication_classes.
    Redirects the browser to the frontend success/failure pages.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

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
        success_base = settings.SEP_FRONTEND_SUCCESS_URL
        failure_base = settings.SEP_FRONTEND_FAILURE_URL
        try:
            payment = services.handle_sep_callback(data=data)
        except services.FinanceError:
            return redirect(failure_base)

        if payment.status == Payment.Status.SUCCEEDED:
            sep = "&" if "?" in success_base else "?"
            return redirect(f"{success_base}{sep}payment_id={payment.pk}")

        sep = "&" if "?" in failure_base else "?"
        return redirect(f"{failure_base}{sep}payment_id={payment.pk}")
