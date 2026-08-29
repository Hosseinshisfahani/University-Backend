from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.finance import services
from apps.finance.models import LedgerEntry, Payment

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


@override_settings(SEP_SANDBOX_MODE=True)
class SepPaymentFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sepuser", password="s3cret")
        self.client = APIClient()

    def _login_cookies(self):
        # Use cookie JWT login so initiate works under CookieJWTAuthentication.
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "sepuser", "password": "s3cret"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        return response

    def test_initiate_sandbox_creates_pending_payment(self):
        self._login_cookies()
        response = self.client.post(
            reverse("finance:sep-initiate"),
            {"amount": "150000", "purpose": "wallet-topup"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["sandbox"])
        self.assertIn("Token=", body["redirect_url"])
        self.assertTrue(body["provider_ref"].startswith("SEP-"))

        payment = Payment.objects.get(pk=body["payment"]["id"])
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.provider, Payment.Provider.SEP)
        self.assertEqual(payment.provider_ref, body["provider_ref"])
        self.assertIn("sep_token_request", payment.metadata)
        self.assertIn("sep_token_response", payment.metadata)
        self.assertIn("sep_token", payment.metadata)

    def test_callback_success_credits_wallet_idempotently(self):
        payment = services.create_payment(
            user=self.user,
            amount=Decimal("75000"),
            provider=Payment.Provider.SEP,
            provider_ref="SEP-TEST-RES-001",
            purpose="topup",
        )
        callback = {
            "ResNum": "SEP-TEST-RES-001",
            "RefNum": "SANDBOX-REF-001",
            "State": "OK",
        }
        result = services.handle_sep_callback(data=callback)
        self.assertEqual(result.status, Payment.Status.SUCCEEDED)
        wallet = services.get_or_create_wallet(self.user)
        self.assertEqual(wallet.balance, Decimal("75000"))
        self.assertEqual(LedgerEntry.objects.filter(wallet=wallet).count(), 1)
        self.assertIn("sep_callback", result.metadata)
        self.assertIn("sep_verify_response", result.metadata)

        # Second callback must not double-credit.
        result2 = services.handle_sep_callback(data=callback)
        self.assertEqual(result2.status, Payment.Status.SUCCEEDED)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal("75000"))
        self.assertEqual(LedgerEntry.objects.filter(wallet=wallet).count(), 1)

    def test_callback_failure_does_not_credit(self):
        payment = services.create_payment(
            user=self.user,
            amount=Decimal("50000"),
            provider=Payment.Provider.SEP,
            provider_ref="SEP-TEST-RES-FAIL",
        )
        result = services.handle_sep_callback(
            data={
                "ResNum": "SEP-TEST-RES-FAIL",
                "RefNum": "",
                "State": "CanceledByUser",
            }
        )
        self.assertEqual(result.status, Payment.Status.FAILED)
        wallet = services.get_or_create_wallet(self.user)
        self.assertEqual(wallet.balance, Decimal("0"))
        self.assertEqual(LedgerEntry.objects.filter(wallet=wallet).count(), 0)

    def test_callback_http_redirects_to_frontend(self):
        payment = services.create_payment(
            user=self.user,
            amount=Decimal("1000"),
            provider=Payment.Provider.SEP,
            provider_ref="SEP-HTTP-OK",
        )
        response = self.client.post(
            reverse("finance:sep-callback"),
            {"ResNum": "SEP-HTTP-OK", "RefNum": "R1", "State": "OK"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("payment_id=", response["Location"])
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
