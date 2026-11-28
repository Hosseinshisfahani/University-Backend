"""Direct-capture checkout: one fulfillment, or a wallet refund when delivery cannot happen."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.kernel.finance.models import LedgerEntry, Payment
from apps.kernel.finance.services import confirm_payment, credit_wallet, get_or_create_wallet
from apps.kernel.tenancy.models import Institute
from apps.modules.booking.models import Appointment, Provider, ServiceType, Slot
from apps.modules.booking.services.booking import confirm_appointment_payment
from apps.modules.lms.models import Course, Enrollment
from apps.modules.lms.services import confirm_enrollment
from apps.modules.shop.models import Order, OrderItem, Product
from apps.modules.shop.services import pay_order_from_wallet

User = get_user_model()


def _gateway(user, institute, purpose, amount):
    payment = Payment.objects.create(
        user=user,
        institute=institute,
        amount=amount,
        purpose=purpose,
        provider=Payment.Provider.VANDAR,
        kind=Payment.Kind.CHECKOUT,
        status=Payment.Status.PENDING,
        provider_ref=f"sandbox-{purpose}",
    )
    return confirm_payment(payment=payment, provider_ref=payment.provider_ref)


class DirectCaptureTests(TestCase):
    def setUp(self):
        self.institute = Institute.objects.get(slug="psy")
        self.user = User.objects.create_user(username="checkout-buyer", password="x", phone="09125550001")
        self.later = timezone.now() + timedelta(minutes=30)

    def _order(self, *, published=True):
        product = Product.objects.create(
            institute=self.institute,
            title="کتاب",
            slug=f"book-{Product.objects.count()}",
            kind=Product.Kind.DIGITAL,
            price=Decimal("4000"),
            is_published=published,
            is_available=True,
        )
        order = Order.objects.create(
            institute=self.institute,
            user=self.user,
            number=f"S{Order.objects.count() + 1}",
            status=Order.Status.PENDING_PAYMENT,
            subtotal=Decimal("4000"),
            total=Decimal("4000"),
            hold_expires_at=self.later,
        )
        OrderItem.objects.create(
            order=order,
            product=product,
            title=product.title,
            kind=product.kind,
            unit_price=Decimal("4000"),
            quantity=1,
            line_total=Decimal("4000"),
        )
        return order, product

    def test_shop_gateway_fulfills_once(self):
        order, _product = self._order()
        payment = _gateway(self.user, self.institute, f"shop.order:{order.pk}", Decimal("4000"))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertEqual(payment.fulfillment_status, Payment.FulfillmentStatus.FULFILLED)
        self.assertEqual(get_or_create_wallet(self.user).balance, Decimal("0"))
        again = confirm_payment(payment=payment)
        self.assertEqual(again.fulfillment_status, Payment.FulfillmentStatus.FULFILLED)
        self.assertEqual(LedgerEntry.objects.filter(entry_type=LedgerEntry.EntryType.REFUND).count(), 0)

    def test_shop_unavailable_product_refunds_to_the_wallet(self):
        order, product = self._order()
        product.is_published = False
        product.save(update_fields=["is_published"])
        payment = _gateway(self.user, self.institute, f"shop.order:{order.pk}", Decimal("4000"))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        self.assertEqual(payment.fulfillment_status, Payment.FulfillmentStatus.REFUNDED_TO_WALLET)
        self.assertEqual(get_or_create_wallet(self.user).balance, Decimal("4000"))

    def test_shop_wallet_payment_wins_and_the_gateway_is_refunded(self):
        order, _product = self._order()
        credit_wallet(
            user=self.user,
            amount=Decimal("4000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="shop-race-seed",
            institute=self.institute,
        )
        pay_order_from_wallet(order=order)
        payment = _gateway(self.user, self.institute, f"shop.order:{order.pk}", Decimal("4000"))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertEqual(order.payment_ref, "wallet")
        self.assertEqual(payment.fulfillment_status, Payment.FulfillmentStatus.REFUNDED_TO_WALLET)
        self.assertEqual(get_or_create_wallet(self.user).balance, Decimal("4000"))
        self.assertEqual(
            LedgerEntry.objects.filter(idempotency_key=f"payment-refund:{payment.pk}").count(),
            1,
        )

    def _enrollment(self):
        course = Course.objects.create(
            institute=self.institute,
            title="دوره",
            slug=f"course-{Course.objects.count()}",
            capacity=10,
            price=Decimal("6000"),
            is_published=True,
        )
        return Enrollment.objects.create(
            workshop=course,
            user=self.user,
            status=Enrollment.Status.PENDING_PAYMENT,
            price_snapshot=Decimal("6000"),
            hold_expires_at=self.later,
        )

    def test_course_gateway_fulfills_once(self):
        enrollment = self._enrollment()
        payment = _gateway(
            self.user, self.institute, f"lms.enrollment:{enrollment.pk}", Decimal("6000")
        )
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, Enrollment.Status.ACTIVE)
        self.assertEqual(payment.fulfillment_status, Payment.FulfillmentStatus.FULFILLED)

    def test_expired_course_hold_refunds_to_the_wallet(self):
        enrollment = self._enrollment()
        enrollment.hold_expires_at = timezone.now() - timedelta(minutes=1)
        enrollment.save(update_fields=["hold_expires_at"])
        payment = _gateway(
            self.user, self.institute, f"lms.enrollment:{enrollment.pk}", Decimal("6000")
        )
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, Enrollment.Status.PENDING_PAYMENT)
        self.assertEqual(payment.fulfillment_status, Payment.FulfillmentStatus.REFUNDED_TO_WALLET)
        self.assertEqual(get_or_create_wallet(self.user).balance, Decimal("6000"))

    def test_course_wallet_payment_wins_and_the_gateway_is_refunded(self):
        enrollment = self._enrollment()
        credit_wallet(
            user=self.user,
            amount=Decimal("6000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="course-race-seed",
            institute=self.institute,
        )
        confirm_enrollment(enrollment=enrollment, payment_ref="wallet")
        payment = _gateway(
            self.user, self.institute, f"lms.enrollment:{enrollment.pk}", Decimal("6000")
        )
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, Enrollment.Status.ACTIVE)
        self.assertEqual(enrollment.payment_ref, "wallet")
        self.assertEqual(payment.fulfillment_status, Payment.FulfillmentStatus.REFUNDED_TO_WALLET)
        self.assertEqual(get_or_create_wallet(self.user).balance, Decimal("6000"))

    def _appointment(self):
        provider_user = User.objects.create_user(
            username=f"provider-{User.objects.count()}",
            password="x",
            phone=f"0912666{User.objects.count():04d}",
        )
        provider = Provider.objects.create(
            institute=self.institute,
            user=provider_user,
            display_name="درمانگر",
        )
        service = ServiceType.objects.create(
            institute=self.institute,
            name="مشاوره",
            slug=f"consult-{ServiceType.objects.count()}",
            modality=ServiceType.Modality.ONLINE,
            duration_minutes=50,
            price=Decimal("8000"),
        )
        start = timezone.now() + timedelta(days=1)
        slot = Slot.objects.create(
            provider=provider,
            service_type=service,
            starts_at=start,
            ends_at=start + timedelta(minutes=50),
            status=Slot.Status.HELD,
            hold_expires_at=self.later,
        )
        return Appointment.objects.create(
            slot=slot,
            customer=self.user,
            provider=provider,
            service_type=service,
            starts_at=start,
            ends_at=start + timedelta(minutes=50),
            status=Appointment.Status.PENDING_PAYMENT,
            price_snapshot=Decimal("8000"),
        )

    def test_booking_gateway_fulfills_once(self):
        appointment = self._appointment()
        payment = _gateway(
            self.user, self.institute, f"booking.appointment:{appointment.pk}", Decimal("8000")
        )
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.CONFIRMED)
        self.assertEqual(payment.fulfillment_status, Payment.FulfillmentStatus.FULFILLED)

    def test_canceled_appointment_refunds_to_the_wallet(self):
        appointment = self._appointment()
        appointment.status = Appointment.Status.CANCELED_BY_PATIENT
        appointment.save(update_fields=["status"])
        payment = _gateway(
            self.user, self.institute, f"booking.appointment:{appointment.pk}", Decimal("8000")
        )
        self.assertEqual(payment.fulfillment_status, Payment.FulfillmentStatus.REFUNDED_TO_WALLET)
        self.assertEqual(get_or_create_wallet(self.user).balance, Decimal("8000"))

    def test_booking_wallet_payment_wins_and_the_gateway_is_refunded(self):
        appointment = self._appointment()
        credit_wallet(
            user=self.user,
            amount=Decimal("8000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="booking-race-seed",
            institute=self.institute,
        )
        confirm_appointment_payment(appointment=appointment, payment_ref="wallet")
        payment = _gateway(
            self.user, self.institute, f"booking.appointment:{appointment.pk}", Decimal("8000")
        )
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.CONFIRMED)
        self.assertEqual(appointment.payment_ref, "wallet")
        self.assertEqual(payment.fulfillment_status, Payment.FulfillmentStatus.REFUNDED_TO_WALLET)
        self.assertEqual(get_or_create_wallet(self.user).balance, Decimal("8000"))
