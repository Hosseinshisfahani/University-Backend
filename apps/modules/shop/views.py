"""Shop catalog, cart, buyer orders, and institute-admin order management."""

from __future__ import annotations

import os
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.kernel.tenancy.permissions import (
    HasMemberRole,
    IsInstituteAdmin,
    IsInstituteAdminOrReadOnly,
)
from apps.kernel.tenancy.scoping import InstituteScopedMixin
from apps.kernel.tenancy.services import is_institute_admin

from . import services
from .models import CartItem, Coupon, Order, OrderItem, Product, ProductCategory
from .serializers import (
    AdminShopOrderUpdateSerializer,
    CancelOrderSerializer,
    CartItemQuantitySerializer,
    CartItemWriteSerializer,
    CheckoutSerializer,
    CouponCodeSerializer,
    CouponSerializer,
    PayOrderSerializer,
    ProductCategorySerializer,
    ProductSerializer,
    ShopOrderSerializer,
)


class ShopPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = "page_size"
    max_page_size = 48


def _shop_error(exc: services.ShopError) -> Response:
    status_code = 403 if exc.code == "forbidden" else 400
    return Response({"code": exc.code, "detail": str(exc), **exc.extra}, status=status_code)


def _paginate(qs, request, *, default_size=25):
    try:
        page = max(1, int(request.query_params.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = min(100, max(1, int(request.query_params.get("page_size", default_size))))
    except (TypeError, ValueError):
        page_size = default_size
    total = qs.count()
    start = (page - 1) * page_size
    return page, page_size, total, qs[start : start + page_size]


def _cart_payload(cart, request) -> dict:
    cart = (
        type(cart)
        .objects.select_related("coupon", "user")
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


class ProductCategoryViewSet(InstituteScopedMixin, viewsets.ModelViewSet):
    required_module = "shop"
    serializer_class = ProductCategorySerializer
    permission_classes = [IsInstituteAdminOrReadOnly]
    pagination_class = None
    lookup_field = "slug"
    queryset = ProductCategory.objects.all()

    def get_queryset(self):
        qs = super().get_queryset()
        if not is_institute_admin(self.request.user, self.institute.slug):
            qs = qs.filter(is_active=True)
        return qs.order_by("sort_order", "name")


class ProductViewSet(InstituteScopedMixin, viewsets.ModelViewSet):
    required_module = "shop"
    serializer_class = ProductSerializer
    permission_classes = [IsInstituteAdminOrReadOnly]
    pagination_class = ShopPagination
    lookup_field = "slug"
    queryset = Product.objects.select_related("category")

    def get_queryset(self):
        qs = super().get_queryset()
        if not is_institute_admin(self.request.user, self.institute.slug):
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
    def download(self, request, slug=None, **kwargs):
        product = self.get_object()
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


class CouponViewSet(InstituteScopedMixin, viewsets.ModelViewSet):
    required_module = "shop"
    serializer_class = CouponSerializer
    permission_classes = [IsAuthenticated, IsInstituteAdmin]
    pagination_class = None
    queryset = Coupon.objects.all()


class CartView(InstituteScopedMixin, APIView):
    required_module = "shop"
    permission_classes = [IsAuthenticated, HasMemberRole]

    def get(self, request, **kwargs):
        cart = services.get_or_create_cart(request.user, self.institute)
        return Response(_cart_payload(cart, request))


class CartItemListView(InstituteScopedMixin, APIView):
    required_module = "shop"
    permission_classes = [IsAuthenticated, HasMemberRole]

    def post(self, request, **kwargs):
        ser = CartItemWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        qs = Product.objects.filter(institute=self.institute)
        if data.get("product_id"):
            product = get_object_or_404(qs, pk=data["product_id"])
        else:
            product = get_object_or_404(qs, slug=data["slug"])
        try:
            services.add_to_cart(
                user=request.user,
                institute=self.institute,
                product=product,
                quantity=data.get("quantity") or 1,
            )
        except services.ShopError as exc:
            return _shop_error(exc)
        cart = services.get_or_create_cart(request.user, self.institute)
        return Response(_cart_payload(cart, request), status=201)


class CartItemDetailView(InstituteScopedMixin, APIView):
    required_module = "shop"
    permission_classes = [IsAuthenticated, HasMemberRole]

    def _item(self, request, pk):
        return get_object_or_404(
            CartItem.objects.select_related("product"),
            pk=pk,
            cart__user=request.user,
            cart__institute=self.institute,
        )

    def patch(self, request, pk, **kwargs):
        item = self._item(request, pk)
        ser = CartItemQuantitySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            services.update_cart_item(item=item, quantity=ser.validated_data["quantity"])
        except services.ShopError as exc:
            return _shop_error(exc)
        cart = services.get_or_create_cart(request.user, self.institute)
        return Response(_cart_payload(cart, request))

    def delete(self, request, pk, **kwargs):
        item = self._item(request, pk)
        services.remove_cart_item(item=item)
        cart = services.get_or_create_cart(request.user, self.institute)
        return Response(_cart_payload(cart, request))


class CartCouponView(InstituteScopedMixin, APIView):
    required_module = "shop"
    permission_classes = [IsAuthenticated, HasMemberRole]

    def post(self, request, **kwargs):
        ser = CouponCodeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        cart = services.get_or_create_cart(request.user, self.institute)
        try:
            services.apply_coupon(cart=cart, code=ser.validated_data["code"])
        except services.ShopError as exc:
            return _shop_error(exc)
        return Response(_cart_payload(cart, request))

    def delete(self, request, **kwargs):
        cart = services.get_or_create_cart(request.user, self.institute)
        services.remove_coupon(cart=cart)
        return Response(_cart_payload(cart, request))


class ShopOrderViewSet(InstituteScopedMixin, viewsets.GenericViewSet):
    """The caller's own orders. Institute-wide management is under admin/."""

    required_module = "shop"
    serializer_class = ShopOrderSerializer
    permission_classes = [IsAuthenticated, HasMemberRole]
    queryset = Order.objects.all()

    def get_queryset(self):
        services.expire_pending_orders(self.request.user, self.institute)
        return (
            super()
            .get_queryset()
            .filter(user=self.request.user)
            .select_related("user", "institute")
            .prefetch_related("items__product")
            .order_by("-created_at")
        )

    def list(self, request, **kwargs):
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    def retrieve(self, request, pk=None, **kwargs):
        order = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(self.get_serializer(order).data)

    def create(self, request, **kwargs):
        ser = CheckoutSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        cart = services.get_or_create_cart(request.user, self.institute)
        try:
            order = services.checkout(cart=cart, shipping=ser.validated_data)
        except services.ShopError as exc:
            return _shop_error(exc)
        order = self.get_queryset().get(pk=order.pk)
        return Response(self.get_serializer(order).data, status=201)

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None, **kwargs):
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
    def gateway(self, request, pk=None, **kwargs):
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
    def cancel(self, request, pk=None, **kwargs):
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


def _admin_orders(institute):
    return (
        Order.objects.filter(institute=institute)
        .select_related("user", "institute")
        .prefetch_related("items__product")
    )


class AdminShopOrderListView(InstituteScopedMixin, APIView):
    required_module = "shop"
    permission_classes = [IsAuthenticated, IsInstituteAdmin]

    def get(self, request, **kwargs):
        qs = _admin_orders(self.institute).order_by("-created_at")
        status = request.query_params.get("status")
        query = (request.query_params.get("q") or "").strip()
        if status:
            qs = qs.filter(status=status)
        if query:
            qs = qs.filter(
                Q(number__icontains=query)
                | Q(user__username__icontains=query)
                | Q(user__first_name__icontains=query)
                | Q(user__last_name__icontains=query)
                | Q(shipping_full_name__icontains=query)
            )
        page, page_size, total, items = _paginate(qs, request)
        return Response(
            {
                "count": total,
                "page": page,
                "page_size": page_size,
                "results": ShopOrderSerializer(items, many=True, context={"request": request}).data,
            }
        )


class AdminShopOrderDetailView(InstituteScopedMixin, APIView):
    required_module = "shop"
    permission_classes = [IsAuthenticated, IsInstituteAdmin]

    def get(self, request, pk: int, **kwargs):
        order = get_object_or_404(_admin_orders(self.institute), pk=pk)
        return Response(ShopOrderSerializer(order, context={"request": request}).data)

    def patch(self, request, pk: int, **kwargs):
        order = get_object_or_404(_admin_orders(self.institute), pk=pk)
        ser = AdminShopOrderUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            order = services.admin_update_order(
                order=order,
                status=data.get("status"),
                tracking_code=data.get("tracking_code"),
                admin_note=data.get("admin_note"),
            )
        except services.ShopError as exc:
            return _shop_error(exc)
        order = get_object_or_404(_admin_orders(self.institute), pk=order.pk)
        return Response(ShopOrderSerializer(order, context={"request": request}).data)


class AdminShopOrderRefundView(InstituteScopedMixin, APIView):
    required_module = "shop"
    permission_classes = [IsAuthenticated, IsInstituteAdmin]

    def post(self, request, pk: int, **kwargs):
        order = get_object_or_404(_admin_orders(self.institute), pk=pk)
        reason = ""
        if isinstance(request.data, dict):
            reason = request.data.get("reason") or ""
        try:
            order = services.cancel_order(order=order, canceled_by="admin", reason=reason)
        except services.ShopError as exc:
            return _shop_error(exc)
        order = get_object_or_404(_admin_orders(self.institute), pk=order.pk)
        return Response(ShopOrderSerializer(order, context={"request": request}).data)


class AdminShopStatsView(InstituteScopedMixin, APIView):
    required_module = "shop"
    permission_classes = [IsAuthenticated, IsInstituteAdmin]

    def get(self, request, **kwargs):
        now = timezone.now()
        paid = Order.objects.filter(institute=self.institute, status__in=services.PAID_STATUSES)
        scoped = Order.objects.filter(institute=self.institute)

        def revenue_since(since):
            return paid.filter(paid_at__gte=since).aggregate(
                total=Coalesce(Sum("total"), Decimal("0")),
                n=Count("id"),
            )

        by_status = {
            row["status"]: row["n"] for row in scoped.values("status").annotate(n=Count("id"))
        }
        top = (
            OrderItem.objects.filter(
                order__institute=self.institute,
                order__status__in=services.PAID_STATUSES,
            )
            .values("title")
            .annotate(
                quantity=Coalesce(Sum("quantity"), 0),
                revenue=Coalesce(Sum("line_total"), Decimal("0")),
            )
            .order_by("-revenue")[:8]
        )
        recent = _admin_orders(self.institute).order_by("-created_at")[:8]
        all_time = paid.aggregate(total=Coalesce(Sum("total"), Decimal("0")), n=Count("id"))
        week = revenue_since(now - timedelta(days=7))
        month = revenue_since(now - timedelta(days=30))
        return Response(
            {
                "revenue_total": str(all_time["total"]),
                "orders_paid_count": all_time["n"],
                "revenue_7d": str(week["total"]),
                "orders_7d": week["n"],
                "revenue_30d": str(month["total"]),
                "orders_30d": month["n"],
                "orders_by_status": by_status,
                "top_products": [
                    {
                        "title": row["title"],
                        "quantity": row["quantity"],
                        "revenue": str(row["revenue"]),
                    }
                    for row in top
                ],
                "recent_orders": ShopOrderSerializer(
                    recent, many=True, context={"request": request}
                ).data,
            }
        )
