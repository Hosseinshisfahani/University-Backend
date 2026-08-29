from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.db import transaction

from .models import User


class UserSerializer(serializers.ModelSerializer):
    groups = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "date_joined",
            "groups",
        ]
        read_only_fields = fields

    def get_groups(self, obj) -> list[str]:
        return list(obj.groups.values_list("name", flat=True))


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    first_name = serializers.CharField(required=False, allow_blank=True, default="", max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, default="", max_length=150)
    phone = serializers.CharField(required=False, allow_blank=True, default="", max_length=32)

    def validate_username(self, value: str) -> str:
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("این نام کاربری قبلاً ثبت شده است.")
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "رمز عبور و تکرار آن یکسان نیستند."})
        validate_password(attrs["password"])
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        from django.contrib.auth.models import Group
        from apps.institutes.psy_institute.models import PatientProfile

        validated_data.pop("password_confirm")
        phone = validated_data.pop("phone", "")
        password = validated_data.pop("password")
        user = User.objects.create_user(password=password, **validated_data)
        group, _ = Group.objects.get_or_create(name="psy_patient")
        user.groups.add(group)
        PatientProfile.objects.get_or_create(user=user, defaults={"phone": phone})
        return user
