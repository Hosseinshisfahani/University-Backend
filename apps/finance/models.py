"""
Platform-wide wallet, ledger, payments, and withdrawals.

Currency: IRR (Rials), integer amounts (0 decimal places).
Toman display conversions belong on the frontend only.

Cross-app rule: other apps must call finance.services — never mutate
Wallet.balance directly. finance must not import domain apps; use opaque
reference strings (e.g. ``psy.appointment:42``).
"""

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


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
        max_length=64, db_index=True, blank=True, verbose_name="مرجع"
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

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "سند دفترکل"
        verbose_name_plural = "اسناد دفترکل"
        indexes = [
            models.Index(fields=["wallet", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.direction} {self.amount} ({self.entry_type})"


class Payment(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELED = "canceled", "Canceled"

    class Provider(models.TextChoices):
        MANUAL = "manual", "Manual / reception"
        SEP = "sep", "SEP (Saman Electronic Payment)"
        GATEWAY = "gateway", "Generic gateway"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name="کاربر",
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
    provider = models.CharField(
        max_length=16,
        choices=Provider.choices,
        default=Provider.SEP,
        verbose_name="درگاه",
    )
    provider_ref = models.CharField(
        max_length=128, blank=True, db_index=True, verbose_name="شناسه درگاه"
    )
    purpose = models.CharField(max_length=64, blank=True, verbose_name="بابت")
    metadata = models.JSONField(default=dict, blank=True, verbose_name="فراداده")
    ledger_entry = models.OneToOneField(
        LedgerEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment",
        verbose_name="سند دفترکل",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "پرداخت"
        verbose_name_plural = "پرداخت ها"

    def __str__(self) -> str:
        return f"Payment<{self.pk}> {self.amount} {self.status}"


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

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "درخواست برداشت"
        verbose_name_plural = "درخواست های برداشت"

    def __str__(self) -> str:
        return f"Withdrawal<{self.pk}> {self.amount} {self.status}"
