from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.kernel.finance import services
from apps.kernel.finance.models import LedgerEntry, Payment
from apps.kernel.finance.vandar_gateway import VandarGatewayError, VandarMoneyResult

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
    PLATFORM_FRONTEND_ORIGIN="https://icqt.ac.ir",
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

    def test_forged_failed_status_still_verifies(self):
        services.create_payment(
            user=self.user,
            amount=Decimal("50000"),
            provider=Payment.Provider.VANDAR,
            provider_ref="sandbox-fail",
        )
        result = services.handle_vandar_callback(
            data={"token": "sandbox-fail", "payment_status": "FAILED"}
        )
        self.assertEqual(result.status, Payment.Status.SUCCEEDED)
        wallet = services.get_or_create_wallet(self.user)
        self.assertEqual(wallet.balance, Decimal("50000"))

    def test_callback_http_redirects_to_the_stored_host(self):
        payment = services.create_payment(
            user=self.user,
            amount=Decimal("1000"),
            provider=Payment.Provider.VANDAR,
            provider_ref="sandbox-http",
        )
        payment.return_host = "pay.example"
        payment.return_path = "/patient/wallet"
        payment.save(update_fields=["return_host", "return_path"])
        response = self.client.get(
            reverse("finance:vandar-callback"),
            {"token": "sandbox-http", "payment_status": "OK"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"https://pay.example/patient/wallet?payment_id={payment.public_id}&status=success", response["Location"])

    def test_unknown_token_goes_to_the_platform_failure_page(self):
        response = self.client.get(
            reverse("finance:vandar-callback"),
            {"token": "missing-token", "payment_status": "OK"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "https://icqt.ac.ir/payment/result?status=failed",
        )

    def test_callback_returns_to_the_originating_institute(self):
        from apps.kernel.tenancy.models import Institute, InstituteDomain

        family = Institute.objects.create(
            slug="family",
            name="خانواده",
            is_active=True,
            enabled_modules=["shop"],
        )
        payment = services.create_payment(
            user=self.user,
            amount=Decimal("1000"),
            provider=Payment.Provider.VANDAR,
            provider_ref="sandbox-family",
            purpose="wallet.topup",
            institute=family,
        )
        payment.return_host = "icqt.ac.ir"
        payment.return_path = "/patient/wallet"
        payment.save(update_fields=["return_host", "return_path", "institute"])

        response = self.client.get(
            reverse("finance:vandar-callback"),
            {"token": "sandbox-family", "payment_status": "OK"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            f"https://icqt.ac.ir/i/family/patient/wallet?payment_id={payment.public_id}&status=success",
            response["Location"],
        )

        InstituteDomain.objects.create(
            institute=family,
            hostname="family.example",
            is_active=True,
            is_canonical=True,
        )
        payment.provider_ref = "sandbox-family-domain"
        payment.trans_id = None
        payment.status = Payment.Status.PENDING
        payment.return_host = "family.example"
        payment.return_path = "/patient/shop/orders"
        payment.save(update_fields=["provider_ref", "trans_id", "status", "return_host", "return_path"])
        with patch(
            "apps.kernel.finance.vandar_gateway.verify_transaction",
            return_value=_vandar_money(success=False, message="failed", amount=payment.amount),
        ):
            response = self.client.get(
                reverse("finance:vandar-callback"),
                {"token": "sandbox-family-domain", "payment_status": "FAILED"},
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            f"https://family.example/patient/shop/orders?payment_id={payment.public_id}&status=failed",
            response["Location"],
        )

    def test_blank_host_standard_institute_uses_platform_origin(self):
        from apps.kernel.finance.views import build_return_url
        from apps.kernel.tenancy.models import Institute

        family = Institute.objects.create(
            slug="family-blank",
            name="خانواده",
            is_active=True,
            frontend_mode="standard",
        )
        payment = services.create_payment(
            user=self.user,
            amount=Decimal("1000"),
            purpose="wallet.topup",
            institute=family,
        )
        payment.return_host = ""
        payment.return_path = "/orders"
        payment.save(update_fields=["return_host", "return_path", "institute"])
        self.assertEqual(
            build_return_url(payment, "success"),
            f"https://icqt.ac.ir/i/family-blank/orders?payment_id={payment.public_id}&status=success",
        )

    @override_settings(PLATFORM_FRONTEND_ORIGIN="")
    def test_empty_platform_origin_does_not_emit_hostless_institute_path(self):
        from apps.kernel.finance.views import build_return_url
        from apps.kernel.tenancy.models import Institute

        family = Institute.objects.create(
            slug="family-empty",
            name="خانواده",
            is_active=True,
            frontend_mode="standard",
        )
        payment = services.create_payment(
            user=self.user,
            amount=Decimal("1000"),
            purpose="wallet.topup",
            institute=family,
        )
        payment.return_host = ""
        payment.return_path = "/orders"
        payment.save(update_fields=["return_host", "return_path", "institute"])
        url = build_return_url(payment, "success")
        self.assertEqual(
            url,
            f"/orders?payment_id={payment.public_id}&status=success",
        )
        self.assertNotIn("/i/", url)

    def test_custom_frontend_keeps_the_stored_path_without_institute_prefix(self):
        from apps.kernel.finance.views import build_return_url
        from apps.kernel.tenancy.models import Institute

        psy = Institute.objects.create(
            slug="psy-return",
            name="روان",
            is_active=True,
            frontend_mode="custom",
        )
        payment = services.create_payment(
            user=self.user,
            amount=Decimal("1000"),
            purpose="wallet.topup",
            institute=psy,
        )
        payment.return_host = ""
        payment.return_path = "/patient/wallet"
        payment.save(update_fields=["return_host", "return_path", "institute"])
        url = build_return_url(payment, "success")
        self.assertEqual(
            url,
            f"https://icqt.ac.ir/patient/wallet?payment_id={payment.public_id}&status=success",
        )
        self.assertNotIn("/i/", url)

    def test_checkout_records_the_institute(self):
        from apps.kernel.tenancy.models import Institute, InstituteDomain

        family = Institute.objects.create(slug="family2", name="خانواده", is_active=True)
        InstituteDomain.objects.create(
            institute=family,
            hostname="family.example",
            is_active=True,
            is_canonical=True,
        )
        result = services.start_checkout(
            user=self.user,
            purpose="shop.order:4",
            amount_irr=Decimal("10000"),
            institute=family,
            return_path="/patient/shop/orders",
            request_host="evil.example",
        )
        payment = result["payment"]
        self.assertEqual(payment.institute_id, family.id)
        self.assertEqual(payment.kind, Payment.Kind.CHECKOUT)
        self.assertEqual(payment.return_host, "family.example")

    def test_verify_timeout_then_settled_inquiry_credits_once(self):
        payment = services.create_payment(
            user=self.user,
            amount=Decimal("75000"),
            provider=Payment.Provider.VANDAR,
            provider_ref="sandbox-inquiry-ok",
        )
        with (
            patch(
                "apps.kernel.finance.vandar_gateway.verify_transaction",
                side_effect=VandarGatewayError("timeout", indeterminate=True),
            ),
            patch(
                "apps.kernel.finance.vandar_gateway.inquire_transaction",
                return_value=_vandar_money(
                    success=True,
                    factor_number=str(payment.public_id),
                    trans_id="inquiry-trans-1",
                ),
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
                "apps.kernel.finance.vandar_gateway.verify_transaction",
                side_effect=VandarGatewayError("HTTP 502", indeterminate=True),
            ),
            patch(
                "apps.kernel.finance.vandar_gateway.inquire_transaction",
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
                "apps.kernel.finance.vandar_gateway.verify_transaction",
                side_effect=VandarGatewayError("timeout", indeterminate=True),
            ),
            patch(
                "apps.kernel.finance.vandar_gateway.inquire_transaction",
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
            services.start_topup(user=self.user, amount=Decimal("1000"), request_host="icqt.ac.ir")
        payment = Payment.objects.get(user=self.user)
        self.assertEqual(payment.status, Payment.Status.CANCELED)
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


class FinanceBoundaryTests(TestCase):
    def test_staff_cannot_list_another_users_payments(self):
        owner = User.objects.create_user(username="payer-owner", password="x")
        staff = User.objects.create_user(username="clerk", password="x", is_staff=True)
        Payment.objects.create(user=owner, amount=1000, purpose="topup")
        client = APIClient()
        client.force_authenticate(staff)
        response = client.get("/api/v1/finance/payments/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_public_purpose_cannot_claim_a_module_reference(self):
        with self.assertRaises(services.FinanceError):
            services.assert_public_purpose("shop.order:4")
        services.assert_public_purpose("wallet-topup")

    def test_return_path_must_be_a_server_chosen_relative_path(self):
        user = User.objects.create_user(username="origin-payer", password="x")
        with self.assertRaises(services.FinanceError):
            services.start_topup(
                user=user,
                amount=Decimal("1000"),
                return_path="https://evil.example/orders",
                request_host="icqt.ac.ir",
            )
