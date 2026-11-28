from django.utils.text import slugify
from rest_framework import serializers

from .models import (
    AvailabilityException,
    LeaveRequest,
    Provider,
    ProviderAvailability,
    ProviderServiceOffer,
    ServiceType,
)


class ServiceTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceType
        fields = [
            "id",
            "name",
            "slug",
            "modality",
            "duration_minutes",
            "price",
            "buffer_minutes",
            "is_active",
            "sort_order",
        ]
        extra_kwargs = {"slug": {"required": False, "allow_blank": True}}

    def create(self, validated_data):
        if not (validated_data.get("slug") or "").strip():
            base = slugify(validated_data["name"]) or "service"
            slug = base
            n = 2
            institute = self.context["institute"]
            while ServiceType.objects.filter(institute=institute, slug=slug).exists():
                slug = f"{base}-{n}"
                n += 1
            validated_data["slug"] = slug
        return super().create(validated_data)


class ProviderSerializer(serializers.ModelSerializer):
    rating_avg = serializers.SerializerMethodField()
    rating_count = serializers.SerializerMethodField()

    class Meta:
        model = Provider
        fields = ["id", "display_name", "is_active", "is_accepting", "rating_avg", "rating_count"]

    def get_rating_avg(self, obj):
        avg = getattr(obj, "rating_avg", None)
        return None if avg is None else round(float(avg), 2)

    def get_rating_count(self, obj):
        return int(getattr(obj, "rating_count", 0) or 0)


class AvailabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProviderAvailability
        fields = ["id", "weekday", "start_time", "end_time", "timezone", "valid_from", "valid_until", "is_active"]

    def validate(self, attrs):
        provider = self.context.get("provider") or getattr(self.instance, "provider", None)
        weekday = attrs.get("weekday", getattr(self.instance, "weekday", None))
        if provider is not None and weekday is not None:
            existing = ProviderAvailability.objects.filter(provider=provider, weekday=weekday)
            if self.instance is not None:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError({"weekday": "برای هر روز فقط یک بازه مجاز است."})
        return attrs


class OfferSerializer(serializers.ModelSerializer):
    service_type = ServiceTypeSerializer(read_only=True)
    service_type_id = serializers.PrimaryKeyRelatedField(
        source="service_type", queryset=ServiceType.objects.all(), write_only=True, required=False
    )
    session_type_id = serializers.IntegerField(required=False, write_only=True)

    def validate(self, attrs):
        legacy_id = attrs.pop("session_type_id", None)
        if legacy_id and "service_type" not in attrs:
            service = ServiceType.objects.filter(pk=legacy_id).first()
            if service is None:
                raise serializers.ValidationError({"session_type_id": "Service type not found."})
            attrs["service_type"] = service
        if self.instance is None and "service_type" not in attrs:
            raise serializers.ValidationError({"service_type_id": "service_type_id is required."})
        return attrs

    class Meta:
        model = ProviderServiceOffer
        fields = ["id", "service_type", "service_type_id", "session_type_id", "is_active"]


class ExceptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AvailabilityException
        fields = ["id", "date", "is_day_off", "start_time", "end_time", "reason"]


class LeaveSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source="provider.display_name", read_only=True)

    class Meta:
        model = LeaveRequest
        fields = [
            "id",
            "provider",
            "provider_name",
            "starts_on",
            "ends_on",
            "start_time",
            "end_time",
            "reason",
            "status",
            "admin_note",
            "reviewed_at",
        ]
        read_only_fields = ["provider", "status", "reviewed_at"]


class BookAppointmentSerializer(serializers.Serializer):
    slot_id = serializers.IntegerField()
    service_type_id = serializers.IntegerField(required=False)
    session_type_id = serializers.IntegerField(required=False)
    customer_id = serializers.IntegerField(required=False)
    payment = serializers.ChoiceField(choices=["pending", "wallet", "offline"], required=False)

    def validate(self, data):
        service_type_id = data.get("service_type_id") or data.get("session_type_id")
        if not service_type_id:
            raise serializers.ValidationError("service_type_id is required.")
        data["service_type_id"] = service_type_id
        return data


class ReviewSubmitSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    body = serializers.CharField(required=False, allow_blank=True)


class ConfirmSerializer(serializers.Serializer):
    payment_ref = serializers.CharField(required=False, default="wallet")


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)


class MoveSerializer(serializers.Serializer):
    new_slot_id = serializers.IntegerField()


class MeetingLinkSerializer(serializers.Serializer):
    meeting_link = serializers.CharField(required=False, allow_blank=True)


class SlotWriteSerializer(serializers.Serializer):
    provider_id = serializers.IntegerField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class RegenerateSerializer(serializers.Serializer):
    provider_id = serializers.IntegerField()
    range_start = serializers.DateField()
    range_end = serializers.DateField()
