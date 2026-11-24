"""Shop events. The module does not import an institute.

Gateway fulfillment stays here and accepts the current and legacy purpose
prefixes published by finance.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.dispatch import Signal, receiver

from apps.kernel.finance.services import SHOP_ORDER_PURPOSE_PREFIXES
from apps.kernel.finance.signals import payment_succeeded

from .models import Order

logger = logging.getLogger(__name__)

order_paid = Signal()
order_shipped = Signal()
order_cancelled = Signal()
order_refunded = Signal()


@receiver(payment_succeeded)
def fulfill_shop_order_on_payment(sender, payment, **kwargs):
    from .services import ShopError, pay_order_from_wallet

    purpose = getattr(payment, "purpose", "") or ""
    prefix = next(
        (item for item in SHOP_ORDER_PURPOSE_PREFIXES if purpose.startswith(item)),
        "",
    )
    if not prefix:
        return
    raw_id = purpose[len(prefix) :]
    if not raw_id.isdigit():
        return
    try:
        order = Order.objects.get(pk=int(raw_id))
    except Order.DoesNotExist:
        logger.warning("gateway payment for missing shop order %s", raw_id)
        return
    if order.status != Order.Status.PENDING_PAYMENT:
        return
    try:
        with transaction.atomic():
            pay_order_from_wallet(
                order=order,
                idempotency_key=f"order-pay:{order.pk}",
                payment_ref=f"vandar:{payment.pk}",
            )
    except ShopError:
        logger.exception("shop order %s was not paid from the gateway deposit", order.pk)
    except Exception:
        logger.exception("shop order %s gateway fulfillment failed", order.pk)
