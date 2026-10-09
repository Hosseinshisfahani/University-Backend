"""Clinic shop: cart, coupons, checkout, wallet or gateway payment, refunds."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.finance import services as finance_services
from apps.finance.models import LedgerEntry, Wallet

from ..models import (
    Cart,
    CartItem,
    Coupon,
    CouponRedemption,
    Order,
    OrderItem,
    PatientProfile,
    Product,
)
from .notify import notify_order

ORDER_HOLD_MINUTES = 30
GATEWAY_HOLD_MINUTES = 60
MAX_QUANTITY = 20

SHIPPING_FIELDS = (
    "full_name",
    "phone",
    "province",
    "city",
    "address",
    "postal_code",
)

PAID_STATUSES = (
    Order.Status.PAID,
    Order.Status.PROCESSING,
    Order.Status.SHIPPED,
    Order.Status.DELIVERED,
)

_PHYSICAL_NEXT = {
    Order.Status.PAID: Order.Status.PROCESSING,
    Order.Status.PROCESSING: Order.Status.SHIPPED,
    Order.Status.SHIPPED: Order.Status.DELIVERED,
}
_DIGITAL_NEXT = {
    Order.Status.PAID: Order.Status.DELIVERED,
}


class ShopError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "shop_error",
        extra: dict | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.extra = extra or {}


def _rial(amount) -> Decimal:
    return Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _shipping_fee() -> Decimal:
    raw = getattr(settings, "PSY_SHOP_SHIPPING_FEE", 0) or 0
    return _rial(raw)


def get_or_create_cart(patient: PatientProfile) -> Cart:
    cart, _ = Cart.objects.get_or_create(patient=patient)
    return cart


def _buyable(product: Product) -> bool:
    return product.is_published and product.is_available


def expire_pending_orders(patient: PatientProfile) -> int:
    """Lazy hold expiry. Pending orders past ``hold_expires_at`` become canceled."""
    now = timezone.now()
    return Order.objects.filter(
        patient=patient,
        status=Order.Status.PENDING_PAYMENT,
        hold_expires_at__isnull=False,
        hold_expires_at__lte=now,
    ).update(
        status=Order.Status.CANCELED,
        canceled_at=now,
        cancellation_reason="hold_expired",
        hold_expires_at=None,
        updated_at=now,
    )


def _pending_coupon_orders(coupon: Coupon, *, exclude_order_id: int | None = None):
    now = timezone.now()
    qs = Order.objects.filter(
        coupon=coupon,
        status=Order.Status.PENDING_PAYMENT,
        hold_expires_at__gt=now,
    )
    if exclude_order_id:
        qs = qs.exclude(pk=exclude_order_id)
    return qs


def _assert_coupon(
    coupon: Coupon,
    subtotal: Decimal,
    patient: PatientProfile,
    *,
    exclude_order_id: int | None = None,
) -> Decimal:
    now = timezone.now()
    if not coupon.is_active:
        raise ShopError("کد تخفیف فعال نیست.", code="coupon_inactive")
    if coupon.starts_at and coupon.starts_at > now:
        raise ShopError("کد تخفیف هنوز شروع نشده است.", code="coupon_not_started")
    if coupon.ends_at and coupon.ends_at <= now:
        raise ShopError("کد تخفیف منقضی شده است.", code="coupon_expired")
    if subtotal < Decimal(coupon.min_order_total):
        raise ShopError(
            "مبلغ سفارش به حداقل این کد تخفیف نرسیده است.",
            code="coupon_min_total",
            extra={"min_order_total": str(coupon.min_order_total)},
        )
    reserved = _pending_coupon_orders(coupon, exclude_order_id=exclude_order_id).count()
    if coupon.max_uses is not None and coupon.used_count + reserved >= coupon.max_uses:
        raise ShopError("سقف استفاده از این کد تخفیف پر شده است.", code="coupon_exhausted")
    user_pending = (
        _pending_coupon_orders(coupon, exclude_order_id=exclude_order_id)
        .filter(patient=patient)
        .count()
    )
    user_used = CouponRedemption.objects.filter(coupon=coupon, patient=patient).count()
    if user_used + user_pending >= coupon.max_uses_per_user:
        raise ShopError(
            "شما قبلاً از این کد تخفیف استفاده کرده‌اید.",
            code="coupon_user_limit",
        )
    if coupon.kind == Coupon.Kind.PERCENT:
        percent = min(Decimal(coupon.value), Decimal(100))
        discount = _rial(subtotal * percent / Decimal(100))
        if coupon.max_discount is not None:
            discount = min(discount, _rial(coupon.max_discount))
    else:
        discount = min(_rial(coupon.value), subtotal)
    if discount < 0:
        discount = Decimal(0)
    return discount


def describe_cart(cart: Cart) -> dict:
    items = list(cart.items.select_related("product", "product__category"))
    subtotal = Decimal(0)
    requires_shipping = False
    for item in items:
        product = item.product
        if not _buyable(product):
            continue
        subtotal += _rial(product.price) * item.quantity
        if product.kind == Product.Kind.PHYSICAL:
            requires_shipping = True
    discount = Decimal(0)
    coupon_error = None
    if cart.coupon_id and subtotal > 0:
        try:
            discount = _assert_coupon(cart.coupon, subtotal, cart.patient)
        except ShopError as exc:
            coupon_error = {"code": exc.code, "detail": str(exc), **exc.extra}
    shipping_fee = _shipping_fee() if requires_shipping else Decimal(0)
    total = max(Decimal(0), subtotal - discount) + shipping_fee
    return {
        "subtotal": subtotal,
        "discount_total": discount,
        "shipping_fee": shipping_fee,
        "total": total,
        "requires_shipping": requires_shipping,
        "coupon_error": coupon_error,
    }


def add_to_cart(*, patient: PatientProfile, product: Product, quantity: int = 1) -> CartItem:
    if quantity < 1:
        raise ShopError("تعداد نامعتبر است.", code="invalid_quantity")
    if not _buyable(product):
        raise ShopError("این محصول قابل خرید نیست.", code="unavailable")
    cart = get_or_create_cart(patient)
    item, created = CartItem.objects.get_or_create(
        cart=cart, product=product, defaults={"quantity": 0}
    )
    if product.kind == Product.Kind.DIGITAL:
        item.quantity = 1
    else:
        item.quantity = min(MAX_QUANTITY, (item.quantity if not created else 0) + quantity)
        if item.quantity < 1:
            item.quantity = 1
    item.save(update_fields=["quantity", "updated_at"])
    return item


def update_cart_item(*, item: CartItem, quantity: int) -> CartItem:
    if quantity < 1 or quantity > MAX_QUANTITY:
        raise ShopError("تعداد نامعتبر است.", code="invalid_quantity")
    if item.product.kind == Product.Kind.DIGITAL:
        quantity = 1
    item.quantity = quantity
    item.save(update_fields=["quantity", "updated_at"])
    return item


def remove_cart_item(*, item: CartItem) -> None:
    item.delete()


def apply_coupon(*, cart: Cart, code: str) -> Cart:
    normalized = (code or "").strip().upper()
    if not normalized:
        raise ShopError("کد تخفیف را وارد کنید.", code="coupon_required")
    try:
        coupon = Coupon.objects.get(code=normalized)
    except Coupon.DoesNotExist as exc:
        raise ShopError("کد تخفیف پیدا نشد.", code="coupon_not_found") from exc
    totals_subtotal = Decimal(0)
    for item in cart.items.select_related("product"):
        if _buyable(item.product):
            totals_subtotal += _rial(item.product.price) * item.quantity
    _assert_coupon(coupon, totals_subtotal, cart.patient)
    cart.coupon = coupon
    cart.save(update_fields=["coupon", "updated_at"])
    return cart


def remove_coupon(*, cart: Cart) -> Cart:
    cart.coupon = None
    cart.save(update_fields=["coupon", "updated_at"])
    return cart


def _shipping_snapshot(shipping: dict | None) -> dict:
    shipping = shipping or {}
    return {key: str(shipping.get(key) or "").strip() for key in SHIPPING_FIELDS}


def _redeem(coupon: Coupon, order: Order, patient: PatientProfile) -> None:
    if CouponRedemption.objects.filter(order=order).exists():
        return
    CouponRedemption.objects.create(coupon=coupon, order=order, patient=patient)
    Coupon.objects.filter(pk=coupon.pk).update(used_count=F("used_count") + 1)


def _release_coupon(order: Order) -> None:
    try:
        redemption = order.coupon_redemption
    except CouponRedemption.DoesNotExist:
        return
    Coupon.objects.filter(pk=redemption.coupon_id, used_count__gt=0).update(
        used_count=F("used_count") - 1
    )
    redemption.delete()


@transaction.atomic
def checkout(*, cart: Cart, shipping: dict | None = None) -> Order:
    # Lock only the cart row. select_related("coupon") is a LEFT JOIN, and
    # PostgreSQL rejects FOR UPDATE on the nullable side of an outer join.
    cart = (
        Cart.objects.select_for_update(of=("self",))
        .select_related("coupon", "patient__user")
        .get(pk=cart.pk)
    )
    items = list(
        cart.items.select_related("product").select_for_update(of=("self",))
    )
    if not items:
        raise ShopError("سبد خرید خالی است.", code="empty_cart")

    subtotal = Decimal(0)
    requires_shipping = False
    for item in items:
        product = item.product
        if not _buyable(product):
            raise ShopError(
                f"«{product.title}» دیگر قابل خرید نیست.",
                code="unavailable",
            )
        if item.quantity < 1 or item.quantity > MAX_QUANTITY:
            raise ShopError("تعداد نامعتبر است.", code="invalid_quantity")
        if product.kind == Product.Kind.DIGITAL and item.quantity != 1:
            raise ShopError("محصول دیجیتال فقط یک‌بار قابل خرید است.", code="invalid_quantity")
        subtotal += _rial(product.price) * item.quantity
        if product.kind == Product.Kind.PHYSICAL:
            requires_shipping = True

    snapshot = _shipping_snapshot(shipping)
    if requires_shipping:
        missing = [key for key in SHIPPING_FIELDS if not snapshot[key]]
        if missing:
            raise ShopError(
                "نشانی ارسال کامل نیست.",
                code="shipping_required",
                extra={"missing": missing},
            )

    discount = Decimal(0)
    coupon = None
    if cart.coupon_id:
        coupon = Coupon.objects.select_for_update().get(pk=cart.coupon_id)
        discount = _assert_coupon(coupon, subtotal, cart.patient)
    shipping_fee = _shipping_fee() if requires_shipping else Decimal(0)
    total = max(Decimal(0), subtotal - discount) + shipping_fee
    now = timezone.now()
    is_free = total == 0
    order = Order.objects.create(
        patient=cart.patient,
        number=f"TMP-{uuid.uuid4().hex[:12]}",
        status=Order.Status.PAID if is_free else Order.Status.PENDING_PAYMENT,
        requires_shipping=requires_shipping,
        shipping_full_name=snapshot["full_name"],
        shipping_phone=snapshot["phone"],
        shipping_province=snapshot["province"],
        shipping_city=snapshot["city"],
        shipping_address=snapshot["address"],
        shipping_postal_code=snapshot["postal_code"],
        subtotal=subtotal,
        discount_total=discount,
        shipping_fee=shipping_fee,
        total=total,
        coupon=coupon,
        coupon_code=coupon.code if coupon else "",
        payment_ref="free" if is_free else "",
        hold_expires_at=None if is_free else now + timedelta(minutes=ORDER_HOLD_MINUTES),
        paid_at=now if is_free else None,
    )
    order.number = f"PSY-{order.pk:06d}"
    order.save(update_fields=["number"])
    OrderItem.objects.bulk_create(
        [
            OrderItem(
                order=order,
                product=item.product,
                title=item.product.title,
                kind=item.product.kind,
                unit_price=_rial(item.product.price),
                quantity=item.quantity,
                line_total=_rial(item.product.price) * item.quantity,
            )
            for item in items
        ]
    )
    if is_free and coupon is not None:
        _redeem(coupon, order, cart.patient)
    cart.items.all().delete()
    if cart.coupon_id:
        cart.coupon = None
        cart.save(update_fields=["coupon", "updated_at"])
    if is_free:
        notify_order(order, "paid")
    return order


def _lock_order(order: Order) -> Order:
    return (
        Order.objects.select_for_update(of=("self",))
        .select_related("patient__user", "coupon")
        .get(pk=order.pk)
    )


@transaction.atomic
def pay_order_from_wallet(
    *,
    order: Order,
    idempotency_key: str,
    payment_ref: str = "wallet",
) -> Order:
    order = _lock_order(order)
    now = timezone.now()
    if order.status in PAID_STATUSES:
        return order
    if (
        order.status == Order.Status.CANCELED
        and order.cancellation_reason == "hold_expired"
    ):
        raise ShopError("مهلت پرداخت سفارش تمام شده است.", code="hold_expired")
    if order.status != Order.Status.PENDING_PAYMENT:
        raise ShopError("این سفارش در انتظار پرداخت نیست.", code="invalid_status")
    if order.hold_expires_at and order.hold_expires_at <= now:
        raise ShopError("مهلت پرداخت سفارش تمام شده است.", code="hold_expired")

    if order.coupon_id:
        _assert_coupon(
            order.coupon,
            Decimal(order.subtotal),
            order.patient,
            exclude_order_id=order.pk,
        )

    amount = _rial(order.total)
    entry = None
    reference = f"psy.order:{order.pk}"
    if amount > 0:
        entry = (
            LedgerEntry.objects.filter(
                reference=reference,
                entry_type=LedgerEntry.EntryType.SHOP_PURCHASE,
                direction=LedgerEntry.Direction.DEBIT,
            )
            .order_by("id")
            .first()
        )
        if entry is None:
            try:
                entry = finance_services.debit_wallet(
                    user=order.patient.user,
                    amount=amount,
                    entry_type=LedgerEntry.EntryType.SHOP_PURCHASE,
                    idempotency_key=idempotency_key,
                    reference=reference,
                    description=order.number,
                )
            except finance_services.InsufficientFunds as exc:
                wallet = finance_services.get_or_create_wallet(order.patient.user)
                balance = _rial(wallet.balance)
                raise ShopError(
                    "موجودی کیف پول کافی نیست.",
                    code="insufficient_funds",
                    extra={
                        "required": str(amount),
                        "balance": str(balance),
                        "shortfall": str(max(Decimal(0), amount - balance)),
                    },
                ) from exc

    order.status = Order.Status.PAID
    order.paid_at = now
    order.hold_expires_at = None
    order.payment_ref = payment_ref or "wallet"
    if entry is not None:
        order.deposit_ledger_ref = f"finance.ledger:{entry.pk}"
    order.save(
        update_fields=[
            "status",
            "paid_at",
            "hold_expires_at",
            "payment_ref",
            "deposit_ledger_ref",
            "updated_at",
        ]
    )
    if order.coupon_id:
        _redeem(order.coupon, order, order.patient)
    notify_order(order, "paid")
    return order


@transaction.atomic
def start_gateway_payment(*, order: Order) -> dict:
    order = _lock_order(order)
    now = timezone.now()
    if order.status in PAID_STATUSES:
        raise ShopError("این سفارش قبلاً پرداخت شده است.", code="already_paid")
    if order.status != Order.Status.PENDING_PAYMENT:
        raise ShopError("این سفارش در انتظار پرداخت نیست.", code="invalid_status")
    if order.hold_expires_at and order.hold_expires_at <= now:
        raise ShopError("مهلت پرداخت سفارش تمام شده است.", code="hold_expired")

    wallet = finance_services.get_or_create_wallet(order.patient.user)
    wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
    balance = _rial(wallet.balance)
    total = _rial(order.total)
    if balance >= total:
        raise ShopError(
            "موجودی کیف پول برای پرداخت این سفارش کافی است.",
            code="wallet_covers",
        )
    shortfall = total - balance
    toman = (shortfall + Decimal(9)) // Decimal(10)
    try:
        result = finance_services.initiate_vandar_payment(
            user=order.patient.user,
            amount=toman,
            purpose=f"psy.order:{order.pk}",
        )
    except finance_services.FinanceError as exc:
        raise ShopError(str(exc), code="gateway_error") from exc

    order.gateway_payment_id = result["payment"].pk
    order.hold_expires_at = now + timedelta(minutes=GATEWAY_HOLD_MINUTES)
    order.save(update_fields=["gateway_payment_id", "hold_expires_at", "updated_at"])
    return result


@transaction.atomic
def cancel_order(*, order: Order, canceled_by: str, reason: str = "") -> Order:
    order = _lock_order(order)
    now = timezone.now()
    if order.status in (Order.Status.CANCELED, Order.Status.REFUNDED):
        return order

    if order.status == Order.Status.PENDING_PAYMENT:
        order.status = Order.Status.CANCELED
        order.canceled_at = now
        order.cancellation_reason = reason
        order.hold_expires_at = None
        order.save(
            update_fields=[
                "status",
                "canceled_at",
                "cancellation_reason",
                "hold_expires_at",
                "updated_at",
            ]
        )
        return order

    patient_refund = (
        canceled_by == "patient"
        and order.status == Order.Status.PAID
        and order.requires_shipping
        and order.shipped_at is None
    )
    admin_refund = canceled_by == "admin" and order.status in PAID_STATUSES
    if not (patient_refund or admin_refund):
        raise ShopError("این سفارش قابل لغو نیست.", code="not_cancelable")

    amount = _rial(order.total)
    if amount > 0:
        entry = finance_services.credit_wallet(
            user=order.patient.user,
            amount=amount,
            entry_type=LedgerEntry.EntryType.REFUND,
            idempotency_key=f"order-refund:{order.pk}",
            reference=f"psy.order:{order.pk}",
            description=f"Refund {order.number}",
        )
        order.refund_ledger_ref = f"finance.ledger:{entry.pk}"
        order.status = Order.Status.REFUNDED
    else:
        order.status = Order.Status.CANCELED
    order.canceled_at = now
    order.cancellation_reason = reason
    order.save(
        update_fields=[
            "status",
            "canceled_at",
            "cancellation_reason",
            "refund_ledger_ref",
            "updated_at",
        ]
    )
    _release_coupon(order)
    return order


@transaction.atomic
def admin_update_order(
    *,
    order: Order,
    status: str | None = None,
    tracking_code: str | None = None,
    admin_note: str | None = None,
) -> Order:
    order = _lock_order(order)
    shipped_now = False
    if admin_note is not None:
        order.admin_note = admin_note
    if tracking_code is not None:
        order.tracking_code = tracking_code.strip()
    if status and status != order.status:
        allowed = _PHYSICAL_NEXT if order.requires_shipping else _DIGITAL_NEXT
        expected = allowed.get(order.status)
        if expected != status:
            raise ShopError(
                "تغییر وضعیت مجاز نیست.",
                code="invalid_transition",
                extra={"from": order.status, "to": status},
            )
        if status == Order.Status.SHIPPED:
            if order.requires_shipping and not (order.tracking_code or "").strip():
                raise ShopError("کد رهگیری را وارد کنید.", code="tracking_required")
            order.shipped_at = timezone.now()
            shipped_now = True
        order.status = status
    order.save()
    if shipped_now:
        notify_order(order, "shipped")
    return order


def user_can_download(user, product: Product) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if product.kind != Product.Kind.DIGITAL or not product.digital_file:
        return False
    if user.is_staff or user.groups.filter(name="psy_admin").exists():
        return True
    patient = getattr(user, "patient_profile", None)
    if patient is None:
        return False
    return OrderItem.objects.filter(
        product=product,
        order__patient=patient,
        order__status__in=PAID_STATUSES,
    ).exists()
