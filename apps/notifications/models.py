"""
Platform-wide SMS and notifications.
"""
from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class SmsMessage(TimeStampedModel):
    class Purpose(models.TextChoices):
        OTP_REGISTER = "otp_register", "OTP ثبت‌نام"
        OTP_PASSWORD_RESET = "otp_password_reset", "OTP بازیابی رمز"
        APPOINTMENT = "appointment", "نوبت"
        ADMIN_MANUAL = "admin_manual", "ارسال دستی ادمین"

    class Status(models.TextChoices):
        QUEUED = "queued", "در صف"
        SENT = "sent", "ارسال شده"
        FAILED = "failed", "ناموفق"
        SKIPPED_NO_PHONE = "skipped_no_phone", "بدون شماره"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sms_messages",
        verbose_name="کاربر",
    )
    phone = models.CharField(max_length=32, verbose_name="شماره")
    purpose = models.CharField(
        max_length=32, choices=Purpose.choices, verbose_name="هدف"
    )
    body = models.TextField(verbose_name="متن")
    provider_sms_id = models.CharField(
        max_length=128, blank=True, verbose_name="شناسه پیامک"
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.QUEUED,
        verbose_name="وضعیت",
    )
    error = models.TextField(blank=True, verbose_name="خطا")
    unique_id = models.CharField(
        max_length=64, blank=True, db_index=True, verbose_name="شناسه یکتا"
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "پیامک"
        verbose_name_plural = "پیامک‌ها"

    def __str__(self) -> str:
        return f"{self.phone} · {self.purpose} · {self.status}"



class OtpChallenge(TimeStampedModel):
    class Purpose(models.TextChoices):
        REGISTER = "otp_register", "OTP ثبت‌نام"
        PASSWORD_RESET = "otp_password_reset", "OTP بازیابی رمز"

    phone = models.CharField(max_length=32, db_index=True, verbose_name="شماره")
    purpose = models.CharField(
        max_length=32, choices=Purpose.choices, verbose_name="هدف"
    )
    code_hash = models.CharField(max_length=64, verbose_name="هش کد")
    expires_at = models.DateTimeField(verbose_name="انقضا")
    attempts = models.PositiveSmallIntegerField(default=0, verbose_name="تلاش")
    consumed_at = models.DateTimeField(null=True, blank=True, verbose_name="مصرف")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "چالش OTP"
        verbose_name_plural = "چالش‌های OTP"
        indexes = [
            models.Index(fields=["phone", "purpose", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.phone} · {self.purpose}"        