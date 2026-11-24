from django.contrib import admin

from .models import OtpChallenge, SmsMessage


@admin.register(SmsMessage)
class SmsMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "phone", "purpose", "status", "user", "created_at")
    list_filter = ("purpose", "status")
    search_fields = ("phone", "provider_sms_id", "body")
    readonly_fields = (
        "user",
        "phone",
        "purpose",
        "body",
        "provider_sms_id",
        "status",
        "error",
        "unique_id",
        "created_at",
        "updated_at",
    )


@admin.register(OtpChallenge)
class OtpChallengeAdmin(admin.ModelAdmin):
    list_display = ("id", "phone", "purpose", "attempts", "expires_at", "consumed_at", "created_at")
    list_filter = ("purpose",)
    search_fields = ("phone",)
    readonly_fields = (
        "phone",
        "purpose",
        "code_hash",
        "expires_at",
        "attempts",
        "consumed_at",
        "created_at",
        "updated_at",
    )