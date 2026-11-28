"""Institute and platform finance summaries.

Gateway checkout is revenue. Wallet top-ups are a liability and stay out of net.
Every figure is filtered by institute.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import Coalesce

from apps.kernel.tenancy.models import Institute

from .models import LedgerEntry, Payment, WithdrawalRequest

_ZERO = Decimal("0")
_PURPOSE_GROUPS = (
    ("shop.order:", "shop"),
    ("lms.enrollment:", "lms"),
    ("booking.appointment:", "booking"),
)
_PURCHASE_TYPES = (
    LedgerEntry.EntryType.SHOP_PURCHASE,
    LedgerEntry.EntryType.WORKSHOP_PURCHASE,
    LedgerEntry.EntryType.APPOINTMENT_CAPTURE,
)


def _money(qs) -> dict:
    row = qs.aggregate(total=Coalesce(Sum("amount"), _ZERO), n=Count("id"))
    return {"total": row["total"], "count": row["n"]}


def institute_summary(institute, date_from, date_to) -> dict:
    ledger = LedgerEntry.objects.filter(
        institute=institute,
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    )
    checkouts = Payment.objects.filter(
        institute=institute,
        kind=Payment.Kind.CHECKOUT,
        status=Payment.Status.SUCCEEDED,
        provider=Payment.Provider.VANDAR,
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    )
    gateway = {}
    gateway_total = _ZERO
    gateway_count = 0
    for prefix, name in _PURPOSE_GROUPS:
        row = _money(checkouts.filter(purpose__startswith=prefix))
        gateway[name] = {"total": str(row["total"]), "count": row["count"]}
        gateway_total += row["total"]
        gateway_count += row["count"]

    purchases = {}
    purchase_total = _ZERO
    for entry_type in _PURCHASE_TYPES:
        row = _money(
            ledger.filter(
                entry_type=entry_type,
                direction=LedgerEntry.Direction.DEBIT,
            )
        )
        purchases[entry_type] = {"total": str(row["total"]), "count": row["count"]}
        purchase_total += row["total"]

    refunds = _money(ledger.filter(entry_type=LedgerEntry.EntryType.REFUND))
    topups = _money(
        Payment.objects.filter(
            institute=institute,
            kind=Payment.Kind.TOPUP,
            status=Payment.Status.SUCCEEDED,
            created_at__date__gte=date_from,
            created_at__date__lte=date_to,
        )
    )
    withdrawals = _money(
        WithdrawalRequest.objects.filter(
            institute=institute,
            status=WithdrawalRequest.Status.PAID,
            created_at__date__gte=date_from,
            created_at__date__lte=date_to,
        )
    )
    capture = _money(ledger.filter(entry_type=LedgerEntry.EntryType.APPOINTMENT_CAPTURE))
    shop = _money(ledger.filter(entry_type=LedgerEntry.EntryType.SHOP_PURCHASE))
    net = gateway_total + purchase_total - refunds["total"]
    return {
        "from": str(date_from),
        "to": str(date_to),
        "institute": institute.slug,
        "gateway_checkout": gateway,
        "gateway_checkout_total": str(gateway_total),
        "gateway_checkout_count": gateway_count,
        "wallet_purchases": purchases,
        "refunds": {"total": str(refunds["total"]), "count": refunds["count"]},
        "topups": {"total": str(topups["total"]), "count": topups["count"]},
        "withdrawals": {"total": str(withdrawals["total"]), "count": withdrawals["count"]},
        "net": str(net),
        "gateway_succeeded_total": str(gateway_total),
        "gateway_succeeded_count": gateway_count,
        "appointment_capture_total": str(capture["total"]),
        "appointment_capture_count": capture["count"],
        "refund_total": str(refunds["total"]),
        "refund_count": refunds["count"],
        "shop_purchase_total": str(shop["total"]),
        "shop_purchase_count": shop["count"],
        "net_appointment_revenue": str(capture["total"] - refunds["total"]),
    }


def platform_summary(date_from, date_to) -> dict:
    rows = [
        institute_summary(institute, date_from, date_to)
        for institute in Institute.objects.filter(is_active=True).order_by("slug")
    ]
    net = sum((Decimal(row["net"]) for row in rows), _ZERO)
    return {"from": str(date_from), "to": str(date_to), "net": str(net), "institutes": rows}
