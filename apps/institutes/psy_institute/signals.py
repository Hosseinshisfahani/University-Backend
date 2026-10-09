"""Settle shop orders when a gateway deposit lands in the wallet."""

from __future__ import annotations

import logging

from django.db import transaction
from django.dispatch import receiver

from apps.finance.signals import payment_succeeded

from .models import Order
from .services.shop import ShopError, pay_order_from_wallet

logger = logging.getLogger(__name__)


@receiver(payment_succeeded)
def fulfill_shop_order_on_payment(sender, payment, **kwargs):
    purpose = getattr(payment, "purpose", "") or ""
    prefix = "psy.order:"
    if not purpose.startswith(prefix):
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
