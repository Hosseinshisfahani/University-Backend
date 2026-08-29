from django.contrib import admin

from .models import LedgerEntry, Payment, Wallet, WithdrawalRequest


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "balance", "is_active", "updated_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("balance",)


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "wallet",
        "direction",
        "amount",
        "entry_type",
        "balance_after",
        "created_at",
    )
    list_filter = ("direction", "entry_type")
    search_fields = ("idempotency_key", "reference")
    readonly_fields = (
        "wallet",
        "direction",
        "amount",
        "balance_after",
        "entry_type",
        "reference",
        "idempotency_key",
        "description",
        "created_at",
        "created_by",
    )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "amount", "status", "provider", "created_at")
    list_filter = ("status", "provider")
    search_fields = ("provider_ref", "user__username")


@admin.register(WithdrawalRequest)
class WithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "wallet", "amount", "status", "created_at")
    list_filter = ("status",)
