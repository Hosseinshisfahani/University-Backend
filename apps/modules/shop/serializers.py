from rest_framework import serializers

from apps.kernel.tenancy.services import extend_payload, person_name

from . import services
from .models import Coupon, Order, OrderItem, Product, ProductCategory


def _strip_file(data, name: str):
    if hasattr(data, "copy"):
        data = data.copy()
    value = data.get(name) if hasattr(data, "get") else None
    if value is None or isinstance(value, str):
        try:
            data.pop(name)
        except (KeyError, AttributeError, TypeError):
            pass
    return data


class ProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = ["id", "name", "slug", "description", "sort_order", "is_active"]


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    category_slug = serializers.CharField(source="category.slug", read_only=True)
    has_digital_file = serializers.SerializerMethodField()
    viewer_can_download = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "title",
            "slug",
            "category",
            "category_name",
            "category_slug",
            "kind",
            "description",
            "body_md",
            "price",
            "compare_at_price",
            "image",
            "digital_file",
            "has_digital_file",
            "viewer_can_download",
            "is_published",
            "is_available",
            "sort_order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {
            "digital_file": {"write_only": True, "required": False},
            "category": {"required": False, "allow_null": True},
        }

    def get_has_digital_file(self, obj) -> bool:
        return bool(obj.digital_file)

    def get_viewer_can_download(self, obj) -> bool:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return services.user_can_download(user, obj)

    def to_internal_value(self, data):
        data = _strip_file(data, "image")
        data = _strip_file(data, "digital_file")
        return super().to_internal_value(data)


class CouponSerializer(serializers.ModelSerializer):
    class Meta:
        model = Coupon
        fields = [
            "id",
            "code",
            "kind",
            "value",
            "max_discount",
            "min_order_total",
            "starts_at",
            "ends_at",
            "max_uses",
            "max_uses_per_user",
            "used_count",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "used_count", "created_at"]

    def validate_code(self, value: str) -> str:
        code = (value or "").strip().upper()
        if not code:
            raise serializers.ValidationError("کد تخفیف لازم است.")
        return code

    def validate(self, attrs):
        kind = attrs.get("kind", getattr(self.instance, "kind", None))
        value = attrs.get("value", getattr(self.instance, "value", None))
        if kind == Coupon.Kind.PERCENT and value is not None:
            if value <= 0 or value > 100:
                raise serializers.ValidationError({"value": "درصد تخفیف باید بین ۱ و ۱۰۰ باشد."})
        if kind == Coupon.Kind.FIXED and value is not None and value <= 0:
            raise serializers.ValidationError({"value": "مبلغ تخفیف باید بیشتر از صفر باشد."})
        return attrs


class OrderItemSerializer(serializers.ModelSerializer):
    product_slug = serializers.CharField(source="product.slug", read_only=True)
    has_digital_file = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "product",
            "product_slug",
            "title",
            "kind",
            "unit_price",
            "quantity",
            "line_total",
            "has_digital_file",
        ]

    def get_has_digital_file(self, obj) -> bool:
        return bool(obj.product_id and obj.product.digital_file)


class ShopOrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    customer_name = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "number",
            "status",
            "customer_name",
            "requires_shipping",
            "shipping_full_name",
            "shipping_phone",
            "shipping_province",
            "shipping_city",
            "shipping_address",
            "shipping_postal_code",
            "subtotal",
            "discount_total",
            "shipping_fee",
            "total",
            "coupon_code",
            "payment_ref",
            "hold_expires_at",
            "paid_at",
            "shipped_at",
            "tracking_code",
            "canceled_at",
            "cancellation_reason",
            "admin_note",
            "items",
            "created_at",
        ]

    def get_customer_name(self, obj) -> str:
        return person_name(obj.institute, obj.user) or ""

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return extend_payload(instance.institute, "shop.order", instance, data)


class CheckoutSerializer(serializers.Serializer):
    full_name = serializers.CharField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(required=False, allow_blank=True, default="")
    province = serializers.CharField(required=False, allow_blank=True, default="")
    city = serializers.CharField(required=False, allow_blank=True, default="")
    address = serializers.CharField(required=False, allow_blank=True, default="")
    postal_code = serializers.CharField(required=False, allow_blank=True, default="")


class CancelOrderSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class CartItemWriteSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(required=False)
    slug = serializers.SlugField(required=False)
    quantity = serializers.IntegerField(required=False, min_value=1, default=1)

    def validate(self, attrs):
        if not attrs.get("product_id") and not attrs.get("slug"):
            raise serializers.ValidationError("محصول مشخص نشده است.")
        return attrs


class CartItemQuantitySerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)


class CouponCodeSerializer(serializers.Serializer):
    code = serializers.CharField()


class AdminShopOrderUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Order.Status.choices, required=False)
    tracking_code = serializers.CharField(required=False, allow_blank=True)
    admin_note = serializers.CharField(required=False, allow_blank=True)
