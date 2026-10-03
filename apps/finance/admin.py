import uuid
from decimal import Decimal

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from . import services
from .forms import WalletAdjustBalanceForm
from .models import LedgerEntry, Payment, Wallet, WithdrawalRequest

admin.sites.AdminSite.site_header = "پنل اختصاصی ادمین مرکز مشاوره"
admin.sites.AdminSite.index_title = "ادیت بخش های مختلف"
admin.sites.AdminSite.site_title = "پنل کامل "


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "balance", "is_active", "updated_at", "adjust_link")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("balance", "adjust_link")
    change_form_template = "admin/finance/wallet/change_form.html"

    @admin.display(description="Manual adjust")
    def adjust_link(self, obj: Wallet):
        if not obj or not obj.pk:
            return "—"
        url = reverse("admin:finance_wallet_adjust", args=[obj.pk])
        return format_html('<a class="button" href="{}">Adjust Balance</a>', url)

    def get_urls(self):
        info = self.opts.app_label, self.opts.model_name
        custom = [
            path(
                "<path:object_id>/adjust/",
                self.admin_site.admin_view(self.adjust_balance_view),
                name="%s_%s_adjust" % info,
            ),
        ]
        return custom + super().get_urls()

    def adjust_balance_view(self, request, object_id):
        wallet = get_object_or_404(Wallet.objects.select_related("user"), pk=object_id)
        if not self.has_change_permission(request, wallet):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied

        if request.method == "POST":
            form = WalletAdjustBalanceForm(request.POST)
            if form.is_valid():
                return self._process_adjustment(request, wallet, form)
        else:
            form = WalletAdjustBalanceForm(
                initial={"action": WalletAdjustBalanceForm.Action.CREDIT}
            )

        context = {
            **self.admin_site.each_context(request),
            "opts": self.opts,
            "original": wallet,
            "title": f"Adjust balance — {wallet.user}",
            "form": form,
            "wallet": wallet,
            "balance_toman": int(wallet.balance) // 10,
            "media": self.media + form.media,
            "has_view_permission": self.has_view_permission(request, wallet),
        }
        return TemplateResponse(
            request,
            "admin/finance/wallet/adjust_balance.html",
            context,
        )

    def _process_adjustment(self, request, wallet: Wallet, form: WalletAdjustBalanceForm):
        action = form.cleaned_data["action"]
        amount_toman = form.cleaned_data["amount"]
        description = form.cleaned_data["description"].strip()
        amount_rial = Decimal(int(amount_toman) * 10)
        idempotency_key = f"admin-adj-{wallet.id}-{uuid.uuid4()}"
        reference = f"admin.manual:{request.user.id}"
        kwargs = {
            "user": wallet.user,
            "amount": amount_rial,
            "entry_type": LedgerEntry.EntryType.ADJUSTMENT,
            "idempotency_key": idempotency_key,
            "reference": reference,
            "description": description,
            "created_by": request.user,
        }

        try:
            if action == WalletAdjustBalanceForm.Action.CREDIT:
                entry = services.credit_wallet(**kwargs)
                verb = "credited"
            else:
                entry = services.debit_wallet(**kwargs)
                verb = "debited"
        except services.InsufficientFunds:
            messages.error(
                request,
                (
                    f"Insufficient balance. Current balance is "
                    f"{wallet.balance} Rials; cannot debit "
                    f"{amount_rial} Rials ({amount_toman} Toman)."
                ),
            )
            return HttpResponseRedirect(
                reverse("admin:finance_wallet_adjust", args=[wallet.pk])
            )
        except services.FinanceError as exc:
            messages.error(request, str(exc))
            return HttpResponseRedirect(
                reverse("admin:finance_wallet_adjust", args=[wallet.pk])
            )

        wallet.refresh_from_db()
        messages.success(
            request,
            (
                f"Wallet {verb} by {amount_toman} Toman "
                f"({amount_rial} Rials). New balance: {wallet.balance} Rials "
                f"(ledger #{entry.pk})."
            ),
        )
        return HttpResponseRedirect(
            reverse("admin:finance_wallet_change", args=[wallet.pk])
        )


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

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "amount", "status", "provider", "created_at")
    list_filter = ("status", "provider")
    search_fields = ("provider_ref", "user__username")


@admin.register(WithdrawalRequest)
class WithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "wallet", "amount", "status", "created_at")
    list_filter = ("status",)
