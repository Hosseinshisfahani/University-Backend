from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.finance import services
from apps.finance.models import LedgerEntry, Payment
from apps.finance.vandar_gateway import VandarGatewayError, VandarMoneyResult

User = get_user_model()


class FinanceServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="payer", password="x")

    def test_credit_and_debit(self):
        services.credit_wallet(
            user=self.user,
            amount=Decimal("100000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="dep-1",
        )
        wallet = services.get_or_create_wallet(self.user)
        self.assertEqual(wallet.balance, Decimal("100000"))

        services.debit_wallet(
            user=self.user,
            amount=Decimal("40000"),
            entry_type=LedgerEntry.EntryType.APPOINTMENT_CAPTURE,
            idempotency_key="cap-1",
        )
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal("60000"))

    def test_idempotent_credit(self):
        services.credit_wallet(
            user=self.user,
            amount=Decimal("5000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="same-key",
        )
        services.credit_wallet(
            user=self.user,
            amount=Decimal("5000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="same-key",
        )
        wallet = services.get_or_create_wallet(self.user)
        self.assertEqual(wallet.balance, Decimal("5000"))
        self.assertEqual(LedgerEntry.objects.count(), 1)

    def test_confirm_payment_credits_wallet(self):
        payment = services.create_payment(
            user=self.user, amount=Decimal("25000"), purpose="test"
        )
        services.confirm_payment(payment=payment, provider_ref="SEP-1")
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        wallet = services.get_or_create_wallet(self.user)
        self.assertEqual(wallet.balance, Decimal("25000"))

    def test_insufficient_funds(self):
        with self.assertRaises(services.InsufficientFunds):
            services.debit_wallet(
                user=self.user,
                amount=Decimal("1"),
                entry_type=LedgerEntry.EntryType.WITHDRAWAL,
                idempotency_key="fail-1",
            )


def _vandar_money(**kwargs):
    data = {
        "success": False,
        "indeterminate": False,
        "confirm_required": False,
        "amount": Decimal("75000"),
        "trans_id": "trans-1",
        "message": "ok",
    }
    data.update(kwargs)
    return VandarMoneyResult(**data)


@override_settings(
    VANDAR_SANDBOX_MODE=True,
    VANDAR_FRONTEND_SUCCESS_URL="http://localhost:3000/patient/wallet/payment/success",
    VANDAR_FRONTEND_FAILURE_URL="http://localhost:3000/patient/wallet/payment/failure",
)
class VandarPaymentFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="vandaruser", password="s3cret")
        self.client = APIClient()

    def _login(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "vandaruser", "password": "s3cret"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_initiate_converts_toman_to_rial(self):
        self._login()
        response = self.client.post(
            reverse("finance:vandar-initiate"),
            {"amount": "15000", "purpose": "wallet-topup"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["sandbox"])
        self.assertTrue(body["provider_ref"].startswith("sandbox-"))
        payment = Payment.objects.get(pk=body["payment"]["id"])
        self.assertEqual(payment.amount, Decimal("150000"))
        self.assertEqual(payment.provider, Payment.Provider.VANDAR)
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.metadata["vandar_token_request"]["amount"], 150000)
        self.assertEqual(payment.metadata["vandar_token_request"]["api_key"], "***")

    def test_initiate_rejects_under_100_toman(self):
        self._login()
        response = self.client.post(
            reverse("finance:vandar-initiate"),
            {"amount": "50"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_callback_success_credits_once(self):
        payment = services.create_payment(
            user=self.user,
            amount=Decimal("75000"),
            provider=Payment.Provider.VANDAR,
            provider_ref="sandbox-ok",
        )
        callback = {"token": "sandbox-ok", "payment_status": "OK"}
        result = services.handle_vandar_callback(data=callback)
        self.assertEqual(result.status, Payment.Status.SUCCEEDED)
        wallet = services.get_or_create_wallet(self.user)
        self.assertEqual(wallet.balance, Decimal("75000"))
        self.assertEqual(LedgerEntry.objects.filter(wallet=wallet).count(), 1)

        result2 = services.handle_vandar_callback(data=callback)
        self.assertEqual(result2.status, Payment.Status.SUCCEEDED)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal("75000"))
        self.assertEqual(LedgerEntry.objects.filter(wallet=wallet).count(), 1)

    def test_callback_failed_does_not_credit(self):
        services.create_payment(
            user=self.user,
            amount=Decimal("50000"),
            provider=Payment.Provider.VANDAR,
            provider_ref="sandbox-fail",
        )
        result = services.handle_vandar_callback(
            data={"token": "sandbox-fail", "payment_status": "FAILED"}
        )
        self.assertEqual(result.status, Payment.Status.FAILED)
        wallet = services.get_or_create_wallet(self.user)
        self.assertEqual(wallet.balance, Decimal("0"))

    def test_callback_http_redirects_to_frontend(self):
        services.create_payment(
            user=self.user,
            amount=Decimal("1000"),
            provider=Payment.Provider.VANDAR,
            provider_ref="sandbox-http",
        )
        response = self.client.get(
            reverse("finance:vandar-callback"),
            {"token": "sandbox-http", "payment_status": "OK"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("payment_id=", response["Location"])
        self.assertIn("/patient/wallet/payment/success", response["Location"])

    def test_verify_timeout_then_settled_inquiry_credits_once(self):
        services.create_payment(
            user=self.user,
            amount=Decimal("75000"),
            provider=Payment.Provider.VANDAR,
            provider_ref="sandbox-inquiry-ok",
        )
        with (
            patch(
                "apps.finance.vandar_gateway.verify_transaction",
                side_effect=VandarGatewayError("timeout", indeterminate=True),
            ),
            patch(
                "apps.finance.vandar_gateway.inquire_transaction",
                return_value=_vandar_money(success=True),
            ),
        ):
            result = services.handle_vandar_callback(
                data={"token": "sandbox-inquiry-ok", "payment_status": "OK"}
            )
        self.assertEqual(result.status, Payment.Status.SUCCEEDED)
        wallet = services.get_or_create_wallet(self.user)
        self.assertEqual(wallet.balance, Decimal("75000"))

    def test_verify_timeout_then_failed_inquiry_does_not_credit(self):
        services.create_payment(
            user=self.user,
            amount=Decimal("75000"),
            provider=Payment.Provider.VANDAR,
            provider_ref="sandbox-inquiry-fail",
        )
        with (
            patch(
                "apps.finance.vandar_gateway.verify_transaction",
                side_effect=VandarGatewayError("HTTP 502", indeterminate=True),
            ),
            patch(
                "apps.finance.vandar_gateway.inquire_transaction",
                return_value=_vandar_money(message="failed"),
            ),
        ):
            result = services.handle_vandar_callback(
                data={"token": "sandbox-inquiry-fail", "payment_status": "OK"}
            )
        self.assertEqual(result.status, Payment.Status.FAILED)
        wallet = services.get_or_create_wallet(self.user)
        self.assertEqual(wallet.balance, Decimal("0"))

    def test_verify_and_inquiry_timeout_stays_indeterminate(self):
        services.create_payment(
            user=self.user,
            amount=Decimal("75000"),
            provider=Payment.Provider.VANDAR,
            provider_ref="sandbox-unknown",
        )
        with (
            patch(
                "apps.finance.vandar_gateway.verify_transaction",
                side_effect=VandarGatewayError("timeout", indeterminate=True),
            ),
            patch(
                "apps.finance.vandar_gateway.inquire_transaction",
                side_effect=VandarGatewayError("timeout", indeterminate=True),
            ),
        ):
            result = services.handle_vandar_callback(
                data={"token": "sandbox-unknown", "payment_status": "OK"}
            )
        self.assertEqual(result.status, Payment.Status.INDETERMINATE)
        wallet = services.get_or_create_wallet(self.user)
        self.assertEqual(wallet.balance, Decimal("0"))

    @override_settings(VANDAR_SANDBOX_MODE=False, VANDAR_API_KEY="test-key", VANDAR_CALLBACK_URL="")
    def test_live_initiate_requires_callback_url(self):
        with self.assertRaises(services.FinanceError):
            services.initiate_vandar_payment(user=self.user, amount=Decimal("100"))
        payment = Payment.objects.get(user=self.user)
        self.assertEqual(payment.status, Payment.Status.FAILED)
        wallet = services.get_or_create_wallet(self.user)
        self.assertEqual(wallet.balance, Decimal("0"))


class WalletAdminAdjustBalanceTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_superuser(
            username="finance-admin",
            email="finance-admin@example.com",
            password="s3cret",
        )
        self.user = User.objects.create_user(username="wallet-owner", password="x")
        self.wallet = services.get_or_create_wallet(self.user)
        self.client = self.client_class()
        self.client.force_login(self.staff)

    def _adjust_url(self):
        return reverse("admin:finance_wallet_adjust", args=[self.wallet.pk])

    def test_credit_writes_adjustment_ledger_and_updates_balance(self):
        response = self.client.post(
            self._adjust_url(),
            {
                "action": "credit",
                "amount": "1500",
                "description": "Reception cash deposit",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal("15000"))
        entry = LedgerEntry.objects.get(wallet=self.wallet)
        self.assertEqual(entry.direction, LedgerEntry.Direction.CREDIT)
        self.assertEqual(entry.entry_type, LedgerEntry.EntryType.ADJUSTMENT)
        self.assertEqual(entry.amount, Decimal("15000"))
        self.assertEqual(entry.reference, f"admin.manual:{self.staff.id}")
        self.assertTrue(entry.idempotency_key.startswith(f"admin-adj-{self.wallet.id}-"))
        self.assertEqual(entry.description, "Reception cash deposit")
        self.assertEqual(entry.created_by_id, self.staff.id)

    def test_debit_requires_sufficient_balance(self):
        services.credit_wallet(
            user=self.user,
            amount=Decimal("10000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="seed-1",
        )
        response = self.client.post(
            self._adjust_url(),
            {
                "action": "debit",
                "amount": "2000",
                "description": "Too large",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal("10000"))
        self.assertEqual(
            LedgerEntry.objects.filter(
                entry_type=LedgerEntry.EntryType.ADJUSTMENT
            ).count(),
            0,
        )

    def test_debit_succeeds_with_sufficient_balance(self):
        services.credit_wallet(
            user=self.user,
            amount=Decimal("50000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="seed-2",
        )
        response = self.client.post(
            self._adjust_url(),
            {
                "action": "debit",
                "amount": "1200",
                "description": "Correction",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal("38000"))
        entry = LedgerEntry.objects.get(entry_type=LedgerEntry.EntryType.ADJUSTMENT)
        self.assertEqual(entry.direction, LedgerEntry.Direction.DEBIT)
        self.assertEqual(entry.amount, Decimal("12000"))

    def test_balance_field_stays_readonly_on_change_form(self):
        response = self.client.get(
            reverse("admin:finance_wallet_change", args=[self.wallet.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Adjust Balance")
        # Django renders readonly balance as plain text, not an editable input.
        self.assertNotContains(
            response,
            'name="balance"',
        )
