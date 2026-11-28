"""Settle Vandar payments that never received a clean callback."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.kernel.finance import services
from apps.kernel.finance.checkout import handler_for
from apps.kernel.finance.models import Payment, PaymentEvent
from apps.kernel.finance.vandar_gateway import VandarGatewayError, inquire_transaction


class Command(BaseCommand):
    help = "Inquire on stuck Vandar payments and cancel checkouts that never received a token."

    def handle(self, *args, **options):
        now = timezone.now()
        pending_before = now - timedelta(minutes=20)
        created_before = now - timedelta(minutes=30)
        stuck = Payment.objects.filter(
            provider=Payment.Provider.VANDAR,
            status=Payment.Status.PENDING,
            updated_at__lt=pending_before,
        )
        unsure = Payment.objects.filter(
            provider=Payment.Provider.VANDAR,
            status=Payment.Status.INDETERMINATE,
        )
        abandoned = Payment.objects.filter(
            provider=Payment.Provider.VANDAR,
            status=Payment.Status.CREATED,
            provider_ref="",
            created_at__lt=created_before,
        )
        settled = 0
        for payment in list(stuck) + list(unsure):
            if self._reconcile(payment):
                settled += 1
        canceled = 0
        for payment in abandoned:
            if self._cancel_created(payment):
                canceled += 1
        self.stdout.write(f"reconciled={settled} canceled={canceled}")

    def _reconcile(self, payment: Payment) -> bool:
        if not payment.provider_ref:
            return False
        try:
            result = inquire_transaction(
                token=payment.provider_ref,
                expected_amount=payment.amount,
                expected_factor=str(payment.public_id),
            )
        except VandarGatewayError as exc:
            PaymentEvent.objects.create(
                payment=payment,
                kind=PaymentEvent.Kind.RECONCILE,
                payload={"error": str(exc), "indeterminate": exc.indeterminate},
            )
            if not exc.indeterminate:
                services.mark_payment_failed(payment=payment, reason=str(exc))
                return True
            return False
        PaymentEvent.objects.create(
            payment=payment,
            kind=PaymentEvent.Kind.RECONCILE,
            payload={
                "success": result.success,
                "message": result.message,
                "trans_id": result.trans_id,
            },
        )
        if result.success and result.factor_number == str(payment.public_id) and result.trans_id:
            if (
                Payment.objects.exclude(pk=payment.pk)
                .filter(trans_id=result.trans_id)
                .exists()
            ):
                services.mark_payment_failed(payment=payment, reason="transaction id already used")
                return True
            payment.trans_id = result.trans_id
            payment.card_masked = (result.card_number or "")[:32]
            payment.verified_at = timezone.now()
            payment.save(update_fields=["trans_id", "card_masked", "verified_at", "updated_at"])
            services.confirm_payment(payment=payment)
            return True
        if result.indeterminate or result.confirm_required:
            services.mark_payment_indeterminate(payment=payment)
            return False
        services.mark_payment_failed(payment=payment, reason=result.message or "reconcile failed")
        return True

    @transaction.atomic
    def _cancel_created(self, payment: Payment) -> bool:
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if payment.status != Payment.Status.CREATED or payment.provider_ref:
            return False
        payment.transition(Payment.Status.CANCELED)
        payment.failure_reason = "no token"
        payment.save(update_fields=["status", "failure_reason", "updated_at"])
        pair = handler_for(payment.purpose or "")
        if pair and pair[1] is not None and payment.kind == Payment.Kind.CHECKOUT:
            pair[1](payment)
        return True
