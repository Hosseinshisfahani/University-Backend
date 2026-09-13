from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import OtpChallenge, SmsMessage
from .ssmss_client import (
    SsmssError,
    is_iranian_mobile,
    normalize_phone,
    send as provider_send,
    to_ascii_digits,
)


OTP_TTL_SECONDS = 300
OTP_COOLDOWN_SECONDS = 60
OTP_MAX_PER_HOUR = 5
OTP_MAX_ATTEMPTS = 5


def send_sms(
    *,
    phone: str,
    body: str,
    purpose: str,
    user=None,
    unique_id: str = "",
) -> SmsMessage:
    normalized = normalize_phone(phone)
    message = SmsMessage.objects.create(
        user=user if getattr(user, "pk", None) else None,
        phone=normalized or (phone or ""),
        purpose=purpose,
        body=body,
        unique_id=unique_id,
        status=SmsMessage.Status.QUEUED,
    )
    if not is_iranian_mobile(normalized):
        message.status = SmsMessage.Status.SKIPPED_NO_PHONE
        message.error = "شماره موبایل معتبر نیست."
        message.save(update_fields=["status", "error", "updated_at"])
        return message

    try:
        result = provider_send(
            receiver=normalized,
            note=body,
            unique_id=unique_id or "0",
        )
    except SsmssError as exc:
        message.status = SmsMessage.Status.FAILED
        message.error = str(exc)
        message.save(update_fields=["status", "error", "updated_at"])
        return message

    message.status = SmsMessage.Status.SENT
    message.provider_sms_id = ",".join(result.sms_ids)
    message.save(update_fields=["status", "provider_sms_id", "updated_at"])
    return message



class OtpError(Exception):
    pass


def _hash_otp(phone: str, code: str) -> str:
    raw = f"{phone}:{code}:{settings.SECRET_KEY}".encode()
    return hashlib.sha256(raw).hexdigest()


def request_otp(*, phone: str, purpose: str) -> OtpChallenge:
    normalized = normalize_phone(phone)
    if not is_iranian_mobile(normalized):
        raise OtpError("شماره موبایل معتبر نیست.")
    if purpose not in OtpChallenge.Purpose.values:
        raise OtpError("هدف OTP نامعتبر است.")

    now = timezone.now()
    recent = OtpChallenge.objects.filter(phone=normalized, purpose=purpose)
    if recent.filter(created_at__gte=now - timedelta(seconds=OTP_COOLDOWN_SECONDS)).exists():
        raise OtpError("لطفاً کمی بعد دوباره تلاش کنید.")
    if recent.filter(created_at__gte=now - timedelta(hours=1)).count() >= OTP_MAX_PER_HOUR:
        raise OtpError("تعداد درخواست‌ها بیش از حد مجاز است.")

    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = OtpChallenge.objects.create(
        phone=normalized,
        purpose=purpose,
        code_hash=_hash_otp(normalized, code),
        expires_at=now + timedelta(seconds=OTP_TTL_SECONDS),
    )
    send_sms(
        phone=normalized,
        body=f"کد تایید شما: {code}\nاعتبار: ۵ دقیقه",
        purpose=purpose,
        unique_id=f"otp:{purpose}:{challenge.pk}",
    )
    return challenge


def verify_otp(*, phone: str, purpose: str, code: str) -> OtpChallenge:
    normalized = normalize_phone(phone)
    challenge = (
        OtpChallenge.objects.filter(
            phone=normalized,
            purpose=purpose,
            consumed_at__isnull=True,
        )
        .order_by("-created_at")
        .first()
    )
    if challenge is None:
        raise OtpError("کد تایید یافت نشد.")
    if challenge.expires_at < timezone.now():
        raise OtpError("کد تایید منقضی شده است.")
    if challenge.attempts >= OTP_MAX_ATTEMPTS:
        raise OtpError("تعداد تلاش بیش از حد مجاز است.")

    challenge.attempts += 1
    expected = challenge.code_hash
    actual = _hash_otp(normalized, to_ascii_digits(code or "").strip())
    if not hmac.compare_digest(expected, actual):
        challenge.save(update_fields=["attempts", "updated_at"])
        raise OtpError("کد تایید نادرست است.")

    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=["attempts", "consumed_at", "updated_at"])
    return challenge