"""
Platform-wide wallet, ledger, payments, and withdrawals.

Currency: IRR (Rials), integer amounts (0 decimal places).
Toman display conversions belong on the frontend only.

Cross-app rule: other apps must call finance.services — never mutate
Wallet.balance directly. finance must not import domain apps; use opaque
reference strings (e.g. ``psy.appointment:42``).
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.kernel.core.models import TimeStampedModel


class Wallet(TimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wallet",
        verbose_name="کاربر",
    )
    balance = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=0,
        help_text="Cached IRR balance. Ledger is the source of truth.",
        verbose_name="موجودی",
    )
    is_active = models.BooleanField(default=True, verbose_name="فعال")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "کیف پول"
        verbose_name_plural = "کیف پول ها"
        constraints = [
            models.CheckConstraint(
                condition=Q(balance__gte=0),
                name="finance_wallet_balance_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"Wallet<{self.user_id}> balance={self.balance}"


class LedgerEntry(models.Model):
    class Direction(models.TextChoices):
        CREDIT = "credit", "Credit"
        DEBIT = "debit", "Debit"

    class EntryType(models.TextChoices):
        DEPOSIT = "deposit", "Deposit"
        APPOINTMENT_HOLD = "appointment_hold", "Appointment hold"
        APPOINTMENT_CAPTURE = "appointment_capture", "Appointment capture"
        REFUND = "refund", "Refund"
        FORFEIT = "forfeit", "Forfeit"
        WORKSHOP_PURCHASE = "workshop_purchase", "Workshop purchase"
        SHOP_PURCHASE = "shop_purchase", "Shop purchase"
        WITHDRAWAL = "withdrawal", "Withdrawal"
        WITHDRAWAL_REVERSAL = "withdrawal_reversal", "Withdrawal reversal"
        ADJUSTMENT = "adjustment", "Adjustment"

    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name="entries",
        verbose_name="کیف پول",
    )
    direction = models.CharField(
        max_length=16, choices=Direction.choices, verbose_name="به جهت"
    )
    amount = models.DecimalField(
        max_digits=12, decimal_places=0, verbose_name="مقدار"
    )
    balance_after = models.DecimalField(
        max_digits=12, decimal_places=0, verbose_name="موجودی پس از تراکنش"
    )
    entry_type = models.CharField(
        max_length=32, choices=EntryType.choices, verbose_name="نوع سند"
    )
    reference = models.CharField(
        max_length=128, db_index=True, blank=True, verbose_name="مرجع"
    )
    payment = models.ForeignKey(
        "finance.Payment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries",
        verbose_name="پرداخت",
    )
    idempotency_key = models.CharField(
        max_length=64, unique=True, verbose_name="کلید یکتایی"
    )
    description = models.TextField(blank=True, verbose_name="توضیحات")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ایجاد")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries_created",
        verbose_name="ایجادکننده",
    )
    institute = models.ForeignKey(
        "tenancy.Institute",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="مرکز",
        help_text="Null is platform-wide activity, not an implicit psy row.",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "سند دفترکل"
        verbose_name_plural = "اسناد دفترکل"
        indexes = [
            models.Index(fields=["wallet", "-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="finance_ledger_amount_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.direction} {self.amount} ({self.entry_type})"


class Payment(TimeStampedModel):
    class Status(models.TextChoices):
        CREATED = "created", "Created"
        PENDING = "pending", "Pending"
        INDETERMINATE = "indeterminate", "Indeterminate"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELED = "canceled", "Canceled"

    class Kind(models.TextChoices):
        TOPUP = "topup", "Wallet top-up"
        CHECKOUT = "checkout", "Direct checkout"

    class FulfillmentStatus(models.TextChoices):
        NONE = "none", "None"
        FULFILLED = "fulfilled", "Fulfilled"
        REFUNDED_TO_WALLET = "refunded_to_wallet", "Refunded to wallet"

    class Provider(models.TextChoices):
        MANUAL = "manual", "Manual / reception"
        VANDAR = "vandar", "Vandar"

    _ALLOWED_TRANSITIONS = {
        Status.CREATED: {Status.PENDING, Status.CANCELED},
        Status.PENDING: {
            Status.SUCCEEDED,
            Status.FAILED,
            Status.CANCELED,
            Status.INDETERMINATE,
        },
        Status.INDETERMINATE: {Status.SUCCEEDED, Status.FAILED},
    }

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name="کاربر",
    )
    amount = models.DecimalField(
        max_digits=12, decimal_places=0, verbose_name="مقدار"
    )
    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        verbose_name="شناسه عمومی",
    )
    kind = models.CharField(
        max_length=16,
        choices=Kind.choices,
        default=Kind.TOPUP,
        verbose_name="نوع",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.CREATED,
        db_index=True,
        verbose_name="وضعیت",
    )
    provider = models.CharField(
        max_length=16,
        choices=Provider.choices,
        default=Provider.VANDAR,
        verbose_name="درگاه",
    )
    provider_ref = models.CharField(
        max_length=128, blank=True, db_index=True, verbose_name="شناسه درگاه"
    )
    trans_id = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        verbose_name="شناسه تراکنش",
    )
    card_masked = models.CharField(max_length=32, blank=True, verbose_name="کارت")
    purpose = models.CharField(max_length=64, blank=True, verbose_name="بابت")
    return_host = models.CharField(max_length=255, blank=True, verbose_name="میزبان بازگشت")
    return_path = models.CharField(max_length=255, blank=True, verbose_name="مسیر بازگشت")
    metadata = models.JSONField(default=dict, blank=True, verbose_name="فراداده")
    verified_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان تایید")
    fulfilled_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان تحویل")
    fulfillment_status = models.CharField(
        max_length=32,
        choices=FulfillmentStatus.choices,
        default=FulfillmentStatus.NONE,
        verbose_name="وضعیت تحویل",
    )
    failure_reason = models.TextField(blank=True, verbose_name="دلیل شکست")
    ledger_entry = models.OneToOneField(
        LedgerEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="linked_payment",
        verbose_name="سند دفترکل",
    )
    institute = models.ForeignKey(
        "tenancy.Institute",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="مرکز",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "پرداخت"
        verbose_name_plural = "پرداخت ها"
        permissions = [
            ("manage_platform_finance", "Manage platform-wide finance"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(kind="checkout") | Q(institute__isnull=False),
                name="finance_checkout_requires_institute",
            ),
            models.UniqueConstraint(
                fields=["provider", "provider_ref"],
                condition=~Q(provider_ref=""),
                name="finance_payment_provider_ref_uniq",
            ),
            models.UniqueConstraint(
                fields=["purpose"],
                condition=Q(
                    kind="checkout",
                    status__in=["created", "pending", "indeterminate", "succeeded"],
                ),
                name="finance_payment_one_open_checkout",
            ),
        ]

    def transition(self, new_status: str) -> None:
        allowed = self._ALLOWED_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Cannot move payment from {self.status} to {new_status}."
            )
        self.status = new_status

    def __str__(self) -> str:
        return f"Payment<{self.pk}> {self.amount} {self.status}"


class PaymentEvent(models.Model):
    class Kind(models.TextChoices):
        INITIATE = "initiate", "Initiate"
        CALLBACK = "callback", "Callback"
        VERIFY = "verify", "Verify"
        INQUIRY = "inquiry", "Inquiry"
        RECONCILE = "reconcile", "Reconcile"

    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name="events",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "رویداد پرداخت"
        verbose_name_plural = "رویدادهای پرداخت"

    def __str__(self) -> str:
        return f"{self.kind} payment={self.payment_id}"


class WithdrawalRequest(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        PAID = "paid", "Paid"

    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name="withdrawals",
        verbose_name="کیف پول",
    )
    amount = models.DecimalField(
        max_digits=12, decimal_places=0, verbose_name="مقدار"
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        verbose_name="وضعیت",
    )
    bank_details = models.JSONField(default=dict, verbose_name="اطلاعات بانکی")
    ticket_reference = models.CharField(
        max_length=64,
        blank=True,
        help_text="Opaque ref e.g. psy.ticket:55 — no FK into domain apps.",
        verbose_name="مرجع تیکت",
    )
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="withdrawals_processed",
        verbose_name="پردازش‌کننده",
    )
    ledger_hold_entry = models.ForeignKey(
        LedgerEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="سند مسدودی",
    )
    ledger_finalize_entry = models.ForeignKey(
        LedgerEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="سند نهایی",
    )
    rejection_reason = models.TextField(blank=True, verbose_name="دلیل رد")
    institute = models.ForeignKey(
        "tenancy.Institute",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="مرکز",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "درخواست برداشت"
        verbose_name_plural = "درخواست های برداشت"

    def __str__(self) -> str:
        return f"Withdrawal<{self.pk}> {self.amount} {self.status}"
