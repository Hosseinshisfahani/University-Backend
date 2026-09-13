from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from .models import OtpChallenge, SmsMessage
from .services import OtpError, request_otp, send_sms, verify_otp
from .ssmss_client import is_iranian_mobile, normalize_phone, to_ascii_digits

User = get_user_model()


class SendSmsSandboxTests(TestCase):
    @override_settings(SMS_SANDBOX_MODE=True)
    def test_sandbox_send_creates_sent_row(self):
        msg = send_sms(
            phone="09121234567",
            body="تست",
            purpose=SmsMessage.Purpose.ADMIN_MANUAL,
        )
        self.assertEqual(msg.status, SmsMessage.Status.SENT)
        self.assertTrue(msg.provider_sms_id.startswith("sandbox-"))

    @override_settings(SMS_SANDBOX_MODE=True)
    def test_invalid_phone_is_skipped(self):
        msg = send_sms(phone="123", body="x", purpose=SmsMessage.Purpose.ADMIN_MANUAL)
        self.assertEqual(msg.status, SmsMessage.Status.SKIPPED_NO_PHONE)

    def test_persian_digits_normalize_to_ascii(self):
        self.assertEqual(to_ascii_digits("۰۹۱۲"), "0912")
        self.assertEqual(normalize_phone("۰۹۱۲۱۲۳۴۵۶۷"), "09121234567")
        self.assertTrue(is_iranian_mobile(normalize_phone("۰۹۹۴۰۹۵۰۶۵۰")))

    @override_settings(SMS_SANDBOX_MODE=True)
    def test_persian_phone_sends_sms(self):
        msg = send_sms(
            phone="۰۹۱۲۱۲۳۴۵۶۷",
            body="تست",
            purpose=SmsMessage.Purpose.ADMIN_MANUAL,
        )
        self.assertEqual(msg.status, SmsMessage.Status.SENT)
        self.assertEqual(msg.phone, "09121234567")


def _code_from_sms(phone: str) -> str:
    body = SmsMessage.objects.filter(phone=phone).latest("created_at").body
    return body.split(":")[1].split()[0].strip()


class OtpTests(TestCase):
    @override_settings(SMS_SANDBOX_MODE=True)
    def test_request_and_verify(self):
        request_otp(phone="09121234567", purpose=OtpChallenge.Purpose.REGISTER)
        code = _code_from_sms("09121234567")
        challenge = verify_otp(
            phone="09121234567",
            purpose=OtpChallenge.Purpose.REGISTER,
            code=code,
        )
        self.assertIsNotNone(challenge.consumed_at)

    @override_settings(SMS_SANDBOX_MODE=True)
    def test_wrong_code_then_reuse_fails_after_consume(self):
        request_otp(phone="09120000000", purpose=OtpChallenge.Purpose.REGISTER)
        code = _code_from_sms("09120000000")
        with self.assertRaises(OtpError):
            verify_otp(phone="09120000000", purpose=OtpChallenge.Purpose.REGISTER, code="000000")
        verify_otp(phone="09120000000", purpose=OtpChallenge.Purpose.REGISTER, code=code)
        with self.assertRaises(OtpError):
            verify_otp(phone="09120000000", purpose=OtpChallenge.Purpose.REGISTER, code=code)

    @override_settings(SMS_SANDBOX_MODE=True)
    def test_cooldown(self):
        request_otp(phone="09121111111", purpose=OtpChallenge.Purpose.REGISTER)
        with self.assertRaises(OtpError):
            request_otp(phone="09121111111", purpose=OtpChallenge.Purpose.REGISTER)

    @override_settings(SMS_SANDBOX_MODE=True)
    def test_expired_code(self):
        challenge = request_otp(phone="09123333333", purpose=OtpChallenge.Purpose.PASSWORD_RESET)
        OtpChallenge.objects.filter(pk=challenge.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(OtpError):
            verify_otp(
                phone="09123333333",
                purpose=OtpChallenge.Purpose.PASSWORD_RESET,
                code=_code_from_sms("09123333333"),
            )


@override_settings(SMS_SANDBOX_MODE=True)
class AdminSmsApiTests(TestCase):
    def setUp(self):
        for name in ("psy_admin", "psy_therapist", "psy_patient"):
            Group.objects.get_or_create(name=name)
        self.admin = User.objects.create_user(
            username="sms_admin", password="x", phone="09120000001"
        )
        self.admin.groups.add(Group.objects.get(name="psy_admin"))
        self.staff = User.objects.create_user(
            username="sms_staff", password="x", phone="09120000002", is_staff=True
        )
        self.patient = User.objects.create_user(
            username="sms_patient",
            password="x",
            phone="09121112233",
            first_name="Ali",
        )
        self.patient.groups.add(Group.objects.get(name="psy_patient"))
        self.therapist = User.objects.create_user(
            username="sms_therapist", password="x", phone="09124445566"
        )
        self.therapist.groups.add(Group.objects.get(name="psy_therapist"))
        self.no_phone = User.objects.create_user(username="sms_nophone", password="x")
        self.no_phone.groups.add(Group.objects.get(name="psy_patient"))
        self.client = APIClient()

    def test_admin_lists_recipients_and_sends(self):
        self.client.force_authenticate(self.admin)
        listed = self.client.get(reverse("notifications:admin-recipients"))
        self.assertEqual(listed.status_code, 200)
        phones = {row["phone"] for row in listed.json()["results"]}
        self.assertIn("09121112233", phones)
        self.assertIn("09124445566", phones)
        self.assertNotIn("", phones)

        sent = self.client.post(
            reverse("notifications:admin-send"),
            {"user_ids": [self.patient.pk], "message": "سلام از ادمین"},
            format="json",
        )
        self.assertEqual(sent.status_code, 200)
        self.assertEqual(sent.json()["sent"], 1)
        row = SmsMessage.objects.get(user=self.patient)
        self.assertEqual(row.purpose, SmsMessage.Purpose.ADMIN_MANUAL)
        self.assertEqual(row.body, "سلام از ادمین")
        self.assertEqual(row.status, SmsMessage.Status.SENT)

    def test_staff_can_list_recipients(self):
        self.client.force_authenticate(self.staff)
        listed = self.client.get(reverse("notifications:admin-recipients"))
        self.assertEqual(listed.status_code, 200)

    def test_patient_is_forbidden(self):
        self.client.force_authenticate(self.patient)
        listed = self.client.get(reverse("notifications:admin-recipients"))
        self.assertEqual(listed.status_code, 403)
        sent = self.client.post(
            reverse("notifications:admin-send"),
            {"user_ids": [self.therapist.pk], "message": "nope"},
            format="json",
        )
        self.assertEqual(sent.status_code, 403)
