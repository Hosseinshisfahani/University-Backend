"""Shop catalog, cart, and patient order API.

Clinic-admin order management lives in ``admin_api.py``.
Money movement stays in ``services.shop``.
"""

from __future__ import annotations

import os

from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import CartItem, Coupon, Order, OrderItem, Product, ProductCategory
from .permissions import IsPatient, IsPsyAdmin, IsPsyAdminOrReadOnly

PSY_ADMIN_GROUP = "psy_admin"


def _is_clinic_admin(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.is_staff or user.groups.filter(name=PSY_ADMIN_GROUP).exists()


def _shop_error(exc: services.ShopError) -> Response:
    status_code = 403 if exc.code == "forbidden" else 400
    return Response({"code": exc.code, "detail": str(exc), **exc.extra}, status=status_code)


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


class ShopPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = "page_size"
    max_page_size = 48


class ProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "sort_order",
            "is_active",
        ]


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
                raise serializers.ValidationError(
                    {"value": "درصد تخفیف باید بین ۱ و ۱۰۰ باشد."}
                )
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
    patient_name = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "number",
            "status",
            "patient_name",
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

    def get_patient_name(self, obj) -> str:
        user = obj.patient.user
        full = f"{user.first_name} {user.last_name}".strip()
        return full or user.username


class CheckoutSerializer(serializers.Serializer):
    full_name = serializers.CharField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(required=False, allow_blank=True, default="")
    province = serializers.CharField(required=False, allow_blank=True, default="")
    city = serializers.CharField(required=False, allow_blank=True, default="")
    address = serializers.CharField(required=False, allow_blank=True, default="")
    postal_code = serializers.CharField(required=False, allow_blank=True, default="")


class PayOrderSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField(max_length=64)


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


def _cart_payload(cart, request) -> dict:
    cart = (
        type(cart)
        .objects.select_related("coupon", "patient")
        .prefetch_related("items__product__category")
        .get(pk=cart.pk)
    )
    totals = services.describe_cart(cart)
    product_ser = ProductSerializer(
        [item.product for item in cart.items.all()],
        many=True,
        context={"request": request},
    )
    by_id = {row["id"]: row for row in product_ser.data}
    items = []
    for item in cart.items.all():
        unit = item.product.price
        items.append(
            {
                "id": item.id,
                "quantity": item.quantity,
                "line_total": str(unit * item.quantity),
                "buyable": item.product.is_published and item.product.is_available,
                "product": by_id.get(item.product_id),
            }
        )
    coupon = None
    if cart.coupon_id and not totals["coupon_error"]:
        coupon = {
            "id": cart.coupon_id,
            "code": cart.coupon.code,
            "kind": cart.coupon.kind,
            "value": str(cart.coupon.value),
        }
    elif cart.coupon_id:
        coupon = {"id": cart.coupon_id, "code": cart.coupon.code}
    return {
        "id": cart.id,
        "items": items,
        "coupon": coupon,
        "coupon_error": totals["coupon_error"],
        "subtotal": str(totals["subtotal"]),
        "discount_total": str(totals["discount_total"]),
        "shipping_fee": str(totals["shipping_fee"]),
        "total": str(totals["total"]),
        "requires_shipping": totals["requires_shipping"],
    }


class ProductCategoryViewSet(viewsets.ModelViewSet):
    serializer_class = ProductCategorySerializer
    permission_classes = [IsPsyAdminOrReadOnly]
    pagination_class = None
    lookup_field = "slug"

    def get_queryset(self):
        qs = ProductCategory.objects.all()
        if not _is_clinic_admin(self.request.user):
            qs = qs.filter(is_active=True)
        return qs.order_by("sort_order", "name")


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    permission_classes = [IsPsyAdminOrReadOnly]
    pagination_class = ShopPagination
    lookup_field = "slug"

    def get_queryset(self):
        qs = Product.objects.select_related("category")
        user = self.request.user
        if not _is_clinic_admin(user):
            qs = qs.filter(is_published=True)
        if self.action == "list":
            category = self.request.query_params.get("category")
            kind = self.request.query_params.get("kind")
            query = (self.request.query_params.get("q") or "").strip()
            if category:
                qs = qs.filter(category__slug=category)
            if kind in (Product.Kind.PHYSICAL, Product.Kind.DIGITAL):
                qs = qs.filter(kind=kind)
            if query:
                qs = qs.filter(Q(title__icontains=query) | Q(description__icontains=query))
            ordering = self.request.query_params.get("ordering") or "sort_order"
            allowed = {
                "price",
                "-price",
                "created_at",
                "-created_at",
                "sort_order",
                "title",
                "-title",
            }
            if ordering not in allowed:
                ordering = "sort_order"
            qs = qs.order_by(ordering, "id")
        return qs

    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated])
    def download(self, request, slug=None):
        product = get_object_or_404(Product, slug=slug)
        if not services.user_can_download(request.user, product):
            return Response(
                {"code": "forbidden", "detail": "این فایل برای شما در دسترس نیست."},
                status=403,
            )
        if not product.digital_file:
            return Response({"detail": "فایلی پیوست نشده است."}, status=404)
        filename = os.path.basename(product.digital_file.name)
        return FileResponse(
            product.digital_file.open("rb"),
            as_attachment=True,
            filename=filename,
        )


class CouponViewSet(viewsets.ModelViewSet):
    serializer_class = CouponSerializer
    permission_classes = [IsAuthenticated, IsPsyAdmin]
    pagination_class = None
    queryset = Coupon.objects.all()


class CartView(APIView):
    permission_classes = [IsAuthenticated, IsPatient]

    def get(self, request):
        cart = services.get_or_create_cart(request.user.patient_profile)
        return Response(_cart_payload(cart, request))


class CartItemListView(APIView):
    permission_classes = [IsAuthenticated, IsPatient]

    def post(self, request):
        ser = CartItemWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        qs = Product.objects.all()
        if data.get("product_id"):
            product = get_object_or_404(qs, pk=data["product_id"])
        else:
            product = get_object_or_404(qs, slug=data["slug"])
        try:
            services.add_to_cart(
                patient=request.user.patient_profile,
                product=product,
                quantity=data.get("quantity") or 1,
            )
        except services.ShopError as exc:
            return _shop_error(exc)
        cart = services.get_or_create_cart(request.user.patient_profile)
        return Response(_cart_payload(cart, request), status=201)


class CartItemDetailView(APIView):
    permission_classes = [IsAuthenticated, IsPatient]

    def _item(self, request, pk):
        return get_object_or_404(
            CartItem.objects.select_related("product"),
            pk=pk,
            cart__patient=request.user.patient_profile,
        )

    def patch(self, request, pk):
        item = self._item(request, pk)
        ser = CartItemQuantitySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            services.update_cart_item(item=item, quantity=ser.validated_data["quantity"])
        except services.ShopError as exc:
            return _shop_error(exc)
        cart = services.get_or_create_cart(request.user.patient_profile)
        return Response(_cart_payload(cart, request))

    def delete(self, request, pk):
        item = self._item(request, pk)
        services.remove_cart_item(item=item)
        cart = services.get_or_create_cart(request.user.patient_profile)
        return Response(_cart_payload(cart, request))


class CartCouponView(APIView):
    permission_classes = [IsAuthenticated, IsPatient]

    def post(self, request):
        ser = CouponCodeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        cart = services.get_or_create_cart(request.user.patient_profile)
        try:
            services.apply_coupon(cart=cart, code=ser.validated_data["code"])
        except services.ShopError as exc:
            return _shop_error(exc)
        return Response(_cart_payload(cart, request))

    def delete(self, request):
        cart = services.get_or_create_cart(request.user.patient_profile)
        services.remove_coupon(cart=cart)
        return Response(_cart_payload(cart, request))


class ShopOrderViewSet(viewsets.GenericViewSet):
    serializer_class = ShopOrderSerializer
    permission_classes = [IsAuthenticated, IsPatient]

    def get_queryset(self):
        patient = self.request.user.patient_profile
        services.expire_pending_orders(patient)
        return (
            Order.objects.filter(patient=patient)
            .select_related("patient__user")
            .prefetch_related("items__product")
            .order_by("-created_at")
        )

    def list(self, request):
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    def retrieve(self, request, pk=None):
        order = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(self.get_serializer(order).data)

    def create(self, request):
        ser = CheckoutSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        cart = services.get_or_create_cart(request.user.patient_profile)
        try:
            order = services.checkout(cart=cart, shipping=ser.validated_data)
        except services.ShopError as exc:
            return _shop_error(exc)
        order = self.get_queryset().get(pk=order.pk)
        return Response(self.get_serializer(order).data, status=201)

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        ser = PayOrderSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        order = get_object_or_404(self.get_queryset(), pk=pk)
        try:
            order = services.pay_order_from_wallet(
                order=order,
                idempotency_key=ser.validated_data["idempotency_key"],
            )
        except services.ShopError as exc:
            return _shop_error(exc)
        order = self.get_queryset().get(pk=order.pk)
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"])
    def gateway(self, request, pk=None):
        order = get_object_or_404(self.get_queryset(), pk=pk)
        try:
            result = services.start_gateway_payment(order=order)
        except services.ShopError as exc:
            return _shop_error(exc)
        order.refresh_from_db()
        return Response(
            {
                "redirect_url": result["redirect_url"],
                "provider_ref": result["provider_ref"],
                "sandbox": result["sandbox"],
                "payment_id": result["payment"].pk,
                "order": self.get_serializer(order).data,
            },
            status=201,
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        ser = CancelOrderSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        order = get_object_or_404(self.get_queryset(), pk=pk)
        try:
            order = services.cancel_order(
                order=order,
                canceled_by="patient",
                reason=ser.validated_data.get("reason") or "",
            )
        except services.ShopError as exc:
            return _shop_error(exc)
        order = self.get_queryset().get(pk=order.pk)
        return Response(self.get_serializer(order).data)
