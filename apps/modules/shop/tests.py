from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.institutes.psy_institute.models import PatientProfile
from apps.kernel.finance.models import LedgerEntry, Payment
from apps.kernel.finance.services import confirm_payment, create_payment, credit_wallet, get_or_create_wallet
from apps.kernel.notifications.models import SmsMessage
from apps.kernel.tenancy.models import Institute
from apps.kernel.tenancy.services import grant_roles, is_institute_admin
from apps.modules.shop.models import Cart, Coupon, Order, Product, ProductCategory

User = get_user_model()


class ShopModuleTests(TestCase):
    def setUp(self):
        self.psy = Institute.objects.get(slug="psy")
        self.family = Institute.objects.create(
            slug="family",
            name="خانواده",
            is_active=True,
            enabled_modules=["shop"],
        )
        self.legal = Institute.objects.create(
            slug="legal",
            name="حقوقی",
            is_active=True,
            enabled_modules=["shop"],
        )
        self.admin = User.objects.create_user(username="shop_admin", password="x", phone="09120000001")
        grant_roles(user=self.admin, institute=self.family, roles=["admin"])
        grant_roles(user=self.admin, institute=self.legal, roles=["admin"])
        self.outsider = User.objects.create_user(username="shop_outsider", password="x")
        grant_roles(user=self.outsider, institute=self.legal, roles=["admin"])
        self.member = User.objects.create_user(
            username="shop_member",
            password="x",
            first_name="مهدی",
            last_name="خریدار",
            phone="09120000002",
        )
        grant_roles(user=self.member, institute=self.family, roles=["member"])
        self.psy_member = User.objects.create_user(
            username="shop_psy_member",
            password="x",
            first_name="سارا",
            last_name="خریدار",
            phone="09120000003",
        )
        grant_roles(user=self.psy_member, institute=self.psy, roles=["member"])
        self.category = ProductCategory.objects.create(
            institute=self.family, name="کتاب", slug="books"
        )
        self.product = Product.objects.create(
            institute=self.family,
            category=self.category,
            title="کتاب خانواده",
            slug="shared-book",
            kind=Product.Kind.DIGITAL,
            price=Decimal("5000"),
            digital_file=ContentFile(b"family-file", name="family.txt"),
            is_published=True,
        )
        self.psy_product = Product.objects.create(
            institute=self.psy,
            title="کتاب روان",
            slug="shared-book",
            kind=Product.Kind.DIGITAL,
            price=Decimal("5000"),
            digital_file=ContentFile(b"psy-file", name="psy.txt"),
            is_published=True,
        )
        self.client = APIClient()

    def _cart(self, institute_slug, product):
        self.client.post(
            f"/api/v1/institutes/{institute_slug}/shop/cart/items/",
            {"product_id": product.id, "quantity": 1},
            format="json",
        )

    def _checkout(self, institute_slug):
        return self.client.post(
            f"/api/v1/institutes/{institute_slug}/shop/orders/",
            {},
            format="json",
        )

    def test_same_slug_and_cart_stay_inside_the_institute(self):
        family = self.client.get("/api/v1/institutes/family/shop/products/shared-book/")
        psy = self.client.get("/api/v1/institutes/psy/shop/products/shared-book/")
        self.assertEqual(family.json()["title"], "کتاب خانواده")
        self.assertEqual(psy.json()["title"], "کتاب روان")

        self.client.force_authenticate(self.member)
        self._cart("family", self.product)
        self.assertTrue(Cart.objects.filter(user=self.member, institute=self.family).exists())
        self.assertFalse(Cart.objects.filter(user=self.member, institute=self.psy).exists())
        created = self._checkout("family")
        self.assertEqual(created.status_code, 201)
        order_id = created.json()["id"]
        self.client.force_authenticate(self.admin)
        own = self.client.get(f"/api/v1/institutes/family/shop/admin/orders/{order_id}/")
        foreign = self.client.get(f"/api/v1/institutes/legal/shop/admin/orders/{order_id}/")
        self.assertEqual(own.status_code, 200)
        self.assertEqual(foreign.status_code, 404)

    def test_coupon_download_and_stats_are_scoped(self):
        Coupon.objects.create(
            institute=self.family,
            code="SAVE10",
            kind=Coupon.Kind.FIXED,
            value=Decimal("1000"),
        )
        Coupon.objects.create(
            institute=self.legal,
            code="SAVE10",
            kind=Coupon.Kind.FIXED,
            value=Decimal("1000"),
        )
        self.client.force_authenticate(self.member)
        self._cart("family", self.product)
        applied = self.client.post(
            "/api/v1/institutes/family/shop/cart/coupon/",
            {"code": "SAVE10"},
            format="json",
        )
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(applied.json()["discount_total"], "1000")

        credit_wallet(
            user=self.member,
            amount=Decimal("4000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="shop-member-deposit",
            institute=self.family,
        )
        order = self._checkout("family")
        paid = self.client.post(
            f"/api/v1/institutes/family/shop/orders/{order.json()['id']}/pay/",
            {"idempotency_key": "order-pay-family"},
            format="json",
        )
        self.assertEqual(paid.status_code, 200, paid.content)
        download = self.client.get(
            "/api/v1/institutes/family/shop/products/shared-book/download/"
        )
        foreign_download = self.client.get(
            "/api/v1/institutes/psy/shop/products/shared-book/download/"
        )
        self.assertEqual(download.status_code, 200)
        self.assertEqual(foreign_download.status_code, 403)

        self.client.force_authenticate(self.admin)
        family_stats = self.client.get("/api/v1/institutes/family/shop/admin/stats/")
        legal_stats = self.client.get("/api/v1/institutes/legal/shop/admin/stats/")
        self.assertEqual(family_stats.json()["orders_paid_count"], 1)
        self.assertEqual(legal_stats.json()["orders_paid_count"], 0)

    def test_roles_follow_the_institute_not_a_psychology_profile(self):
        self.assertFalse(is_institute_admin(self.admin, "psy"))
        self.assertFalse(PatientProfile.objects.filter(user=self.member).exists())
        self.client.force_authenticate(self.outsider)
        denied = self.client.post(
            "/api/v1/institutes/family/shop/categories/",
            {"name": "بیگانه", "slug": "foreign"},
            format="json",
        )
        self.assertEqual(denied.status_code, 403)
        self.client.force_authenticate(self.admin)
        created = self.client.post(
            "/api/v1/institutes/family/shop/categories/",
            {"name": "صوتی", "slug": "audio"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        self.client.force_authenticate(self.member)
        self._cart("family", self.product)
        order = self._checkout("family")
        self.assertEqual(order.status_code, 201)
        self.assertEqual(order.json()["customer_name"], "مهدی خریدار")
        self.assertNotIn("patient_name", order.json())

    def test_wallet_gateway_and_refund_are_idempotent(self):
        credit_wallet(
            user=self.member,
            amount=Decimal("5000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="shop-wallet",
            institute=self.family,
        )
        self.client.force_authenticate(self.member)
        self._cart("family", self.product)
        order = self._checkout("family").json()
        paid = self.client.post(
            f"/api/v1/institutes/family/shop/orders/{order['id']}/pay/",
            {"idempotency_key": f"order-pay:{order['id']}"},
            format="json",
        )
        self.assertEqual(paid.json()["status"], "paid")
        self.assertEqual(get_or_create_wallet(self.member).balance, Decimal("0"))

        gateway_product = Product.objects.create(
            institute=self.family,
            title="درگاه",
            slug="gateway-book",
            kind=Product.Kind.DIGITAL,
            price=Decimal("3000"),
            is_published=True,
        )
        legacy_product = Product.objects.create(
            institute=self.psy,
            title="درگاه قدیم",
            slug="legacy-gateway",
            kind=Product.Kind.DIGITAL,
            price=Decimal("3000"),
            is_published=True,
        )
        self._cart("family", gateway_product)
        gateway_order = self._checkout("family").json()
        payment = create_payment(
            user=self.member,
            amount=Decimal("3000"),
            purpose=f"shop.order:{gateway_order['id']}",
        )
        confirm_payment(payment=payment, provider_ref="shop-gateway")
        self.assertEqual(
            Order.objects.get(pk=gateway_order["id"]).status,
            Order.Status.PAID,
        )

        grant_roles(user=self.member, institute=self.psy, roles=["member"])
        self._cart("psy", legacy_product)
        legacy_order = self._checkout("psy").json()
        legacy_payment = create_payment(
            user=self.member,
            amount=Decimal("3000"),
            purpose=f"psy.order:{legacy_order['id']}",
        )
        confirm_payment(payment=legacy_payment, provider_ref="psy-gateway")
        self.assertEqual(
            Order.objects.get(pk=legacy_order["id"]).status,
            Order.Status.PAID,
        )

        self.client.force_authenticate(self.admin)
        first = self.client.post(
            f"/api/v1/institutes/family/shop/admin/orders/{order['id']}/refund/",
            {"reason": "بازگشت"},
            format="json",
        )
        second = self.client.post(
            f"/api/v1/institutes/family/shop/admin/orders/{order['id']}/refund/",
            {"reason": "بازگشت"},
            format="json",
        )
        self.assertEqual(first.json()["status"], "refunded")
        self.assertEqual(second.json()["status"], "refunded")
        self.assertEqual(get_or_create_wallet(self.member).balance, Decimal("5000"))
        self.assertEqual(
            LedgerEntry.objects.filter(idempotency_key=f"order-refund:{order['id']}").count(),
            1,
        )

    def test_order_sms_is_sent_only_for_psy(self):
        physical = Product.objects.create(
            institute=self.psy,
            title="کتاب کاغذی",
            slug="paper",
            kind=Product.Kind.PHYSICAL,
            price=Decimal("0"),
            is_published=True,
        )
        family_physical = Product.objects.create(
            institute=self.family,
            title="کتاب کاغذی خانواده",
            slug="paper",
            kind=Product.Kind.PHYSICAL,
            price=Decimal("0"),
            is_published=True,
        )
        shipping = {
            "full_name": "سارا خریدار",
            "phone": "09120000003",
            "province": "تهران",
            "city": "تهران",
            "address": "خیابان یک",
            "postal_code": "1234567890",
        }
        before = SmsMessage.objects.count()
        self.client.force_authenticate(self.psy_member)
        self._cart("psy", physical)
        psy_order = self.client.post("/api/v1/institutes/psy/shop/orders/", shipping, format="json")
        self.assertEqual(psy_order.status_code, 201, psy_order.content)
        self.assertEqual(SmsMessage.objects.count(), before + 1)

        self.client.force_authenticate(self.member)
        self._cart("family", family_physical)
        family_order = self.client.post(
            "/api/v1/institutes/family/shop/orders/",
            shipping,
            format="json",
        )
        self.assertEqual(family_order.status_code, 201, family_order.content)
        self.assertEqual(SmsMessage.objects.count(), before + 1)

        psy_admin = User.objects.create_user(username="psy_shop_admin", password="x")
        grant_roles(user=psy_admin, institute=self.psy, roles=["admin"])
        self.client.force_authenticate(psy_admin)
        processing = self.client.patch(
            f"/api/v1/institutes/psy/shop/admin/orders/{psy_order.json()['id']}/",
            {"status": "processing"},
            format="json",
        )
        self.assertEqual(processing.status_code, 200, processing.content)
        shipped = self.client.patch(
            f"/api/v1/institutes/psy/shop/admin/orders/{psy_order.json()['id']}/",
            {"status": "shipped", "tracking_code": "TRK1"},
            format="json",
        )
        self.assertEqual(shipped.status_code, 200, shipped.content)
        self.assertEqual(SmsMessage.objects.count(), before + 2)

    def test_legacy_order_payload_matches_the_scoped_order(self):
        product = Product.objects.create(
            institute=self.psy,
            title="برابری",
            slug="parity-book",
            kind=Product.Kind.DIGITAL,
            price=Decimal("0"),
            is_published=True,
        )
        self.client.force_authenticate(self.psy_member)
        self._cart("psy", product)
        created = self._checkout("psy")
        order_id = created.json()["id"]
        scoped = self.client.get(f"/api/v1/institutes/psy/shop/orders/{order_id}/")
        legacy = self.client.get(f"/api/v1/psy/shop/orders/{order_id}/")
        self.assertEqual(scoped.status_code, 200)
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(scoped.json(), legacy.json())
        self.assertIn("patient_name", scoped.json())
        self.assertTrue(scoped.json()["number"].startswith("PSY-"))
        self.assertIsNone(Payment.objects.filter(purpose=f"shop.order:{order_id}").first())
