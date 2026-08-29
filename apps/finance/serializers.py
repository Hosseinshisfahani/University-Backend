from rest_framework import serializers

from .models import LedgerEntry, Payment, Wallet, WithdrawalRequest


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = ["id", "balance", "is_active", "created_at", "updated_at"]
        read_only_fields = fields


class LedgerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerEntry
        fields = [
            "id",
            "direction",
            "amount",
            "balance_after",
            "entry_type",
            "reference",
            "description",
            "created_at",
        ]
        read_only_fields = fields


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            "id",
            "amount",
            "status",
            "provider",
            "provider_ref",
            "purpose",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "provider_ref",
            "created_at",
            "updated_at",
        ]


class CreatePaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=0, min_value=1)
    purpose = serializers.CharField(max_length=64, required=False, allow_blank=True)
    provider = serializers.ChoiceField(
        choices=Payment.Provider.choices,
        default=Payment.Provider.SEP,
    )
    metadata = serializers.JSONField(required=False)


class ConfirmPaymentSerializer(serializers.Serializer):
    provider_ref = serializers.CharField(max_length=128, required=False, allow_blank=True)
    metadata = serializers.JSONField(required=False)


class WithdrawalSerializer(serializers.ModelSerializer):
    class Meta:
        model = WithdrawalRequest
        fields = [
            "id",
            "amount",
            "status",
            "bank_details",
            "ticket_reference",
            "rejection_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "rejection_reason",
            "created_at",
            "updated_at",
        ]


class CreateWithdrawalSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=0, min_value=1)
    bank_details = serializers.JSONField()
    ticket_reference = serializers.CharField(max_length=64, required=False, allow_blank=True)
    idempotency_key = serializers.CharField(max_length=64)


class RejectWithdrawalSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)


class SepInitiateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=0, min_value=1)
    purpose = serializers.CharField(max_length=64, required=False, allow_blank=True)
