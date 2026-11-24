from django.conf import settings
from django.db import models

from apps.kernel.core.storage import private_media_storage
from apps.kernel.tenancy.models import InstituteScopedModel


def product_image_upload(instance, filename: str) -> str:
    return f"shop/{instance.institute.slug}/products/{filename}"


def product_file_upload(instance, filename: str) -> str:
    return f"shop/{instance.institute.slug}/files/{filename}"


class ProductCategory(InstituteScopedModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=50)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["institute", "slug"], name="uniq_shop_category_slug"),
        ]


class Product(InstituteScopedModel):
    class Kind(models.TextChoices):
        PHYSICAL = "physical", "Physical"
        DIGITAL = "digital", "Digital"

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=50)
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.PHYSICAL)
    description = models.TextField(blank=True)
    body_md = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=0)
    compare_at_price = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True)
    image = models.ImageField(upload_to=product_image_upload, blank=True, max_length=500)
    digital_file = models.FileField(
        upload_to=product_file_upload,
        storage=private_media_storage,
        blank=True,
        max_length=500,
    )
    is_published = models.BooleanField(default=False)
    is_available = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "title"]
        constraints = [
            models.UniqueConstraint(fields=["institute", "slug"], name="uniq_shop_product_slug"),
        ]


class Coupon(InstituteScopedModel):
    class Kind(models.TextChoices):
        PERCENT = "percent", "Percent"
        FIXED = "fixed", "Fixed amount"

    code = models.CharField(max_length=40)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    value = models.DecimalField(max_digits=12, decimal_places=0)
    max_discount = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True)
    min_order_total = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    max_uses_per_user = models.PositiveIntegerField(default=1)
    used_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["institute", "code"], name="uniq_shop_coupon_code"),
        ]


class Cart(InstituteScopedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="shop_carts",
    )
    coupon = models.ForeignKey(
        Coupon, on_delete=models.SET_NULL, null=True, blank=True, related_name="carts"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["institute", "user"], name="uniq_shop_cart_user"),
        ]


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="cart_items")
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["cart", "product"], name="uniq_shop_cart_item"),
        ]


class Order(InstituteScopedModel):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Pending payment"
        PAID = "paid", "Paid"
        PROCESSING = "processing", "Processing"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CANCELED = "canceled", "Canceled"
        REFUNDED = "refunded", "Refunded"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="shop_orders",
    )
    number = models.CharField(max_length=20)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT, db_index=True
    )
    requires_shipping = models.BooleanField(default=False)
    shipping_full_name = models.CharField(max_length=120, blank=True)
    shipping_phone = models.CharField(max_length=32, blank=True)
    shipping_province = models.CharField(max_length=64, blank=True)
    shipping_city = models.CharField(max_length=64, blank=True)
    shipping_address = models.TextField(blank=True)
    shipping_postal_code = models.CharField(max_length=20, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    discount_total = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    shipping_fee = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    coupon = models.ForeignKey(
        Coupon, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders"
    )
    coupon_code = models.CharField(max_length=40, blank=True)
    payment_ref = models.CharField(max_length=64, blank=True)
    deposit_ledger_ref = models.CharField(max_length=64, blank=True)
    refund_ledger_ref = models.CharField(max_length=64, blank=True)
    hold_expires_at = models.DateTimeField(null=True, blank=True)
    gateway_payment_id = models.PositiveIntegerField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    tracking_code = models.CharField(max_length=64, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    admin_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["institute", "number"], name="uniq_shop_order_number"),
        ]


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=16)
    unit_price = models.DecimalField(max_digits=12, decimal_places=0)
    quantity = models.PositiveIntegerField()
    line_total = models.DecimalField(max_digits=12, decimal_places=0)

    class Meta:
        ordering = ["id"]


class CouponRedemption(models.Model):
    coupon = models.ForeignKey(Coupon, on_delete=models.PROTECT, related_name="redemptions")
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="coupon_redemption")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="shop_coupon_redemptions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
