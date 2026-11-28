import json
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch
from urllib import error

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.kernel.finance import services
from apps.kernel.finance.models import LedgerEntry, Payment, Wallet
from apps.kernel.finance.reports import institute_summary
from apps.kernel.finance.vandar_gateway import _interpret
from apps.kernel.tenancy.models import Institute, InstituteDomain

User = get_user_model()


class IdempotencyTests(TestCase):
    def test_same_key_for_another_wallet_is_rejected(self):
        owner = User.objects.create_user(username="owner", password="x")
        other = User.objects.create_user(username="other", password="x")
        services.credit_wallet(
            user=owner,
            amount=Decimal("1000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="shared-key",
        )
        with self.assertRaises(services.IdempotencyConflict):
            services.credit_wallet(
                user=other,
                amount=Decimal("1000"),
                entry_type=LedgerEntry.EntryType.DEPOSIT,
                idempotency_key="shared-key",
            )
        self.assertEqual(services.get_or_create_wallet(other).balance, Decimal("0"))
        self.assertEqual(LedgerEntry.objects.count(), 1)


class GatewayInterpretTests(TestCase):
    def test_exact_amount_matches(self):
        result = _interpret(
            {"status": 1, "message": "ok", "amount": "5000", "transId": "t1", "factorNumber": "abc"},
            expected=Decimal("5000"),
            request_payload={},
            sandbox=False,
        )
        self.assertTrue(result.success)
        self.assertEqual(result.factor_number, "abc")
        self.assertEqual(result.trans_id, "t1")

    def test_greater_amount_is_not_success(self):
        result = _interpret(
            {"status": 1, "message": "ok", "amount": "5001", "transId": "t1"},
            expected=Decimal("5000"),
            request_payload={},
            sandbox=False,
        )
        self.assertFalse(result.success)
        self.assertEqual(result.message, "Amount mismatch")

    def test_confirm_required_is_not_success(self):
        result = _interpret(
            {"status": 1, "message": "ConfirmRequired", "amount": "5000"},
            expected=Decimal("5000"),
            request_payload={},
            sandbox=False,
        )
        self.assertTrue(result.confirm_required)
        self.assertFalse(result.success)


@override_settings(VANDAR_SANDBOX_MODE=False, VANDAR_API_KEY="live-key", VANDAR_CALLBACK_URL="https://icqt.ac.ir/cb")
class LiveGatewayTests(TestCase):
    def test_network_error_is_indeterminate(self):
        from apps.kernel.finance import vandar_gateway

        with patch(
            "apps.kernel.finance.vandar_gateway._json_post",
            side_effect=vandar_gateway.VandarGatewayError("down", indeterminate=True),
        ):
            with self.assertRaises(vandar_gateway.VandarGatewayError) as caught:
                vandar_gateway.verify_transaction(token="tok", expected_amount=1000, expected_factor="f")
        self.assertTrue(caught.exception.indeterminate)

    def test_live_verify_reads_the_recorded_body(self):
        from apps.kernel.finance import vandar_gateway

        payload = {
            "status": 1,
            "message": "ok",
            "amount": "1000",
            "transId": "bank-1",
            "factorNumber": "factor-1",
            "cardNumber": "6037-99**-****-1234",
        }
        body = BytesIO(json.dumps(payload).encode())
        response = type("Resp", (), {"read": body.read, "status": 200, "__enter__": lambda self: self, "__exit__": lambda *a: None})()
        with patch("apps.kernel.finance.vandar_gateway.request.urlopen", return_value=response):
            result = vandar_gateway.verify_transaction(
                token="tok",
                expected_amount=1000,
                expected_factor="factor-1",
            )
        self.assertTrue(result.success)
        self.assertEqual(result.trans_id, "bank-1")
        self.assertEqual(result.card_number, "6037-99**-****-1234")


class CallbackSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="cb", password="x")

    def _pending(self, token, amount="10000"):
        payment = services.create_payment(
            user=self.user,
            amount=Decimal(amount),
            provider=Payment.Provider.VANDAR,
            provider_ref=token,
        )
        return payment

    @override_settings(VANDAR_SANDBOX_MODE=False, VANDAR_API_KEY="live-key")
    def test_reused_trans_id_fails_the_second_payment(self):
        from apps.kernel.finance.vandar_gateway import VandarMoneyResult

        first = self._pending("token-a")
        first.trans_id = "bank-shared"
        first.status = Payment.Status.SUCCEEDED
        first.save(update_fields=["trans_id", "status"])
        second = self._pending("token-b")
        money = VandarMoneyResult(
            success=True,
            indeterminate=False,
            confirm_required=False,
            amount=Decimal("10000"),
            trans_id="bank-shared",
            factor_number=str(second.public_id),
            message="ok",
        )
        with patch("apps.kernel.finance.vandar_gateway.verify_transaction", return_value=money):
            result = services.handle_vandar_callback(data={"token": "token-b", "payment_status": "OK"})
        self.assertEqual(result.status, Payment.Status.FAILED)
        self.assertEqual(services.get_or_create_wallet(self.user).balance, Decimal("0"))

    @override_settings(VANDAR_SANDBOX_MODE=True)
    def test_replay_does_not_credit_twice(self):
        payment = self._pending("sandbox-replay", "75000")
        services.handle_vandar_callback(data={"token": "sandbox-replay", "payment_status": "OK"})
        services.handle_vandar_callback(data={"token": "sandbox-replay", "payment_status": "OK"})
        self.assertEqual(services.get_or_create_wallet(self.user).balance, Decimal("75000"))
        self.assertEqual(LedgerEntry.objects.filter(wallet__user=self.user).count(), 1)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)

    @override_settings(VANDAR_SANDBOX_MODE=True)
    def test_callback_is_throttled(self):
        from rest_framework.throttling import ScopedRateThrottle

        previous = ScopedRateThrottle.THROTTLE_RATES
        ScopedRateThrottle.THROTTLE_RATES = {"vandar_callback": "1/min"}
        client = APIClient()
        try:
            first = client.get(reverse("finance:vandar-callback"), {"token": "none"})
            second = client.get(reverse("finance:vandar-callback"), {"token": "none-2"})
        finally:
            ScopedRateThrottle.THROTTLE_RATES = previous
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 429)


class ReportTests(TestCase):
    def test_summary_stays_inside_the_institute(self):
        psy = Institute.objects.get(slug="psy")
        other = Institute.objects.create(slug="other", name="دیگر", is_active=True)
        user = User.objects.create_user(username="rep", password="x")
        services.credit_wallet(
            user=user,
            amount=Decimal("2000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="rep-psy",
            institute=psy,
        )
        services.credit_wallet(
            user=user,
            amount=Decimal("9000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="rep-other",
            institute=other,
        )
        from django.utils import timezone

        today = timezone.localdate()
        summary = institute_summary(psy, today, today)
        self.assertEqual(summary["institute"], "psy")
        self.assertEqual(summary["topups"]["count"], 0)
        self.assertNotIn("9000", summary["net"])


class ResetCommandTests(TestCase):
    def test_dry_run_keeps_rows(self):
        user = User.objects.create_user(username="keep", password="x")
        services.get_or_create_wallet(user)
        call_command("reset_commerce_test_data")
        self.assertEqual(Wallet.objects.count(), 1)

    def test_name_mismatch_refuses(self):
        user = User.objects.create_user(username="keep2", password="x")
        services.get_or_create_wallet(user)
        with self.assertRaises(CommandError):
            call_command(
                "reset_commerce_test_data",
                "--execute",
                "--database-name",
                "not-the-connected-database",
            )
        self.assertEqual(Wallet.objects.count(), 1)

    def test_real_payment_refuses(self):
        user = User.objects.create_user(username="keep3", password="x")
        Payment.objects.create(
            user=user,
            amount=1000,
            provider=Payment.Provider.VANDAR,
            provider_ref="live-token",
            status=Payment.Status.SUCCEEDED,
        )
        name = connection.settings_dict["NAME"]
        with self.assertRaises(CommandError):
            call_command(
                "reset_commerce_test_data",
                "--execute",
                f"--database-name={name}",
            )
        self.assertEqual(Payment.objects.filter(provider_ref="live-token").count(), 1)


class ReconcileTests(TestCase):
    def test_inquiry_confirms_a_pending_payment(self):
        from apps.kernel.finance.vandar_gateway import VandarMoneyResult

        user = User.objects.create_user(username="recon", password="x")
        payment = services.create_payment(
            user=user,
            amount=Decimal("4000"),
            provider=Payment.Provider.VANDAR,
            provider_ref="sandbox-recon",
        )
        from datetime import timedelta

        from django.utils import timezone

        Payment.objects.filter(pk=payment.pk).update(
            updated_at=timezone.now() - timedelta(minutes=30)
        )
        money = VandarMoneyResult(
            success=True,
            indeterminate=False,
            confirm_required=False,
            amount=Decimal("4000"),
            trans_id="recon-trans",
            factor_number=str(payment.public_id),
            message="ok",
        )
        with patch("apps.kernel.finance.management.commands.reconcile_vandar_payments.inquire_transaction", return_value=money):
            call_command("reconcile_vandar_payments")
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(services.get_or_create_wallet(user).balance, Decimal("4000"))


class ConcurrencyTests(TransactionTestCase):
    """Two workers share one ledger row. Row locks are only meaningful on Postgres."""

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("row locks need Postgres")

    def test_two_debits_share_one_entry(self):
        import threading

        user = User.objects.create_user(username="race-debit", password="x")
        services.credit_wallet(
            user=user,
            amount=Decimal("1000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="race-seed",
        )
        connection.close()
        barrier = threading.Barrier(2)
        errors = []

        def worker():
            try:
                barrier.wait(timeout=5)
                services.debit_wallet(
                    user=user,
                    amount=Decimal("1000"),
                    entry_type=LedgerEntry.EntryType.WITHDRAWAL,
                    idempotency_key="race-debit",
                )
            except Exception as exc:
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(LedgerEntry.objects.filter(idempotency_key="race-debit").count(), 1)
        self.assertEqual(services.get_or_create_wallet(user).balance, Decimal("0"))

    @override_settings(VANDAR_SANDBOX_MODE=True)
    def test_two_callbacks_credit_once(self):
        import threading

        user = User.objects.create_user(username="race-callback", password="x")
        payment = Payment.objects.create(
            user=user,
            amount=Decimal("5000"),
            provider=Payment.Provider.VANDAR,
            provider_ref="sandbox-race",
            kind=Payment.Kind.TOPUP,
            status=Payment.Status.PENDING,
            purpose="wallet.topup",
        )
        connection.close()
        barrier = threading.Barrier(2)
        errors = []

        def worker():
            try:
                barrier.wait(timeout=5)
                services.handle_vandar_callback(
                    data={"token": "sandbox-race", "payment_status": "FAILED"}
                )
            except Exception as exc:
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(
            LedgerEntry.objects.filter(idempotency_key=f"payment:{payment.pk}").count(),
            1,
        )
        self.assertEqual(services.get_or_create_wallet(user).balance, Decimal("5000"))
