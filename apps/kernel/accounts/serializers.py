from django.conf import settings
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.db import transaction

from apps.kernel.notifications.models import OtpChallenge
from apps.kernel.notifications.services import OtpError, verify_otp
from apps.kernel.notifications.ssmss_client import is_iranian_mobile, normalize_phone
from apps.kernel.tenancy.models import Institute
from apps.kernel.tenancy.services import TenancyError, grant_roles, memberships_payload

from .models import User


class UserSerializer(serializers.ModelSerializer):
    groups = serializers.SerializerMethodField()
    memberships = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "phone",
            "is_staff",
            "date_joined",
            "groups",
            "memberships",
        ]
        read_only_fields = fields

    def get_groups(self, obj) -> list[str]:
        return list(obj.groups.values_list("name", flat=True))

    def get_memberships(self, obj) -> list[dict]:
        return memberships_payload(obj)


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    first_name = serializers.CharField(required=False, allow_blank=True, default="", max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, default="", max_length=150)
    phone = serializers.CharField(max_length=32)
    otp = serializers.CharField(write_only=True, min_length=6, max_length=6)
    institute = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_username(self, value: str) -> str:
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("این نام کاربری قبلاً ثبت شده است.")
        return value

    def validate_phone(self, value: str) -> str:
        phone = normalize_phone(value)
        if not is_iranian_mobile(phone):
            raise serializers.ValidationError("شماره موبایل معتبر نیست.")
        if User.objects.filter(phone=phone).exists():
            raise serializers.ValidationError("این شماره قبلاً ثبت شده است.")
        return phone

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "رمز عبور و تکرار آن یکسان نیستند."})
        validate_password(attrs["password"])
        otp = attrs.pop("otp")
        try:
            verify_otp(phone=attrs["phone"], purpose=OtpChallenge.Purpose.REGISTER, code=otp)
        except OtpError as exc:
            raise serializers.ValidationError({"otp": str(exc)})
        slug = (attrs.get("institute") or "").strip() or (
            settings.TENANCY_COMPAT_REGISTER_INSTITUTE or ""
        ).strip()
        attrs["institute"] = slug
        if slug:
            institute = Institute.objects.filter(slug=slug, is_active=True).first()
            if institute is None:
                raise serializers.ValidationError({"institute": "مرکز پیدا نشد."})
            attrs["_institute"] = institute
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        validated_data.pop("password_confirm")
        validated_data.pop("institute", None)
        institute = validated_data.pop("_institute", None)
        phone = validated_data.pop("phone", "")
        password = validated_data.pop("password")
        user = User.objects.create_user(password=password, **validated_data)
        if phone:
            user.phone = phone
            user.save(update_fields=["phone"])
        if institute is not None:
            try:
                grant_roles(user=user, institute=institute, roles=["member"])
            except TenancyError as exc:
                raise serializers.ValidationError({"institute": str(exc)})
        return user


class PasswordResetRequestSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32)


class PasswordResetConfirmSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32)
    otp = serializers.CharField(min_length=6, max_length=6)
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "رمز عبور و تکرار آن یکسان نیستند."})
        validate_password(attrs["password"])
        attrs["phone"] = normalize_phone(attrs["phone"])
        return attrs
