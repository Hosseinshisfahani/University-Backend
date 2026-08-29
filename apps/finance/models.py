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
    )
    balance = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=0,
        help_text="Cached IRR balance. Ledger is the source of truth.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

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
    )
    direction = models.CharField(max_length=16, choices=Direction.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=0)
    balance_after = models.DecimalField(max_digits=12, decimal_places=0)
    entry_type = models.CharField(max_length=32, choices=EntryType.choices)
    reference = models.CharField(max_length=64, db_index=True, blank=True)
    idempotency_key = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries_created",
    )

    class Meta:
        ordering = ["-created_at"]
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
    )
    amount = models.DecimalField(max_digits=12, decimal_places=0)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    provider = models.CharField(
        max_length=16,
        choices=Provider.choices,
        default=Provider.SEP,
    )
    provider_ref = models.CharField(max_length=128, blank=True, db_index=True)
    purpose = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ledger_entry = models.OneToOneField(
        LedgerEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment",
    )

    class Meta:
        ordering = ["-created_at"]

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
    )
    amount = models.DecimalField(max_digits=12, decimal_places=0)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    bank_details = models.JSONField(default=dict)
    ticket_reference = models.CharField(
        max_length=64,
        blank=True,
        help_text="Opaque ref e.g. psy.ticket:55 — no FK into domain apps.",
    )
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="withdrawals_processed",
    )
    ledger_hold_entry = models.ForeignKey(
        LedgerEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    ledger_finalize_entry = models.ForeignKey(
        LedgerEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    rejection_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Withdrawal<{self.pk}> {self.amount} {self.status}"
