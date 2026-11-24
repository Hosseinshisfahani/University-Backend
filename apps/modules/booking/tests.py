from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.kernel.finance.models import LedgerEntry
from apps.kernel.finance.services import credit_wallet
from apps.kernel.tenancy.models import Institute
from apps.kernel.tenancy.services import grant_roles
from apps.modules.booking.models import (
    Appointment,
    AppointmentReview,
    Provider,
    ProviderAvailability,
    ProviderServiceOffer,
    ServiceType,
    Slot,
)
from apps.modules.booking.services import book_slot, cancel_appointment, confirm_appointment_payment
from apps.modules.booking.services.slots import regenerate_slots_for_provider
from apps.modules.booking.signals import appointment_confirmed

User = get_user_model()


def institute(slug):
    return Institute.objects.create(
        slug=slug,
        name=slug,
        is_active=True,
        enabled_modules=["booking", "reviews"],
    )


def member(inst, username, role):
    user = User.objects.create_user(username=username, password="x")
    grant_roles(user=user, institute=inst, roles=[role])
    return user


class BookingIsolationTests(TestCase):
    def setUp(self):
        self.a = institute("alpha")
        self.b = institute("beta")
        self.admin = member(self.a, "alpha_admin", "admin")
        self.customer = member(self.a, "alpha_member", "member")
        self.other = member(self.b, "beta_member", "member")
        self.provider_user = member(self.a, "alpha_staff", "staff")
        self.provider = Provider.objects.create(
            institute=self.a, user=self.provider_user, display_name="Alpha"
        )
        self.service = ServiceType.objects.create(
            institute=self.a,
            name="Talk",
            slug="talk",
            modality=ServiceType.Modality.ONLINE,
            duration_minutes=45,
            price=Decimal("100000"),
        )
        ProviderServiceOffer.objects.create(
            provider=self.provider, service_type=self.service, institute=self.a
        )
        start = timezone.now() + timedelta(days=3)
        self.slot = Slot.objects.create(
            provider=self.provider,
            starts_at=start,
            ends_at=start + timedelta(minutes=45),
            status=Slot.Status.OPEN,
            institute=self.a,
        )
        self.client = APIClient()

    def test_lists_do_not_cross_institutes(self):
        self.client.force_authenticate(self.customer)
        booked = self.client.post(
            "/api/v1/institutes/alpha/booking/appointments/",
            {"slot_id": self.slot.id, "service_type_id": self.service.id},
            format="json",
        )
        self.assertEqual(booked.status_code, 201, booked.content)
        self.client.force_authenticate(self.other)
        foreign = self.client.get("/api/v1/institutes/alpha/booking/appointments/")
        self.assertEqual(foreign.status_code, 200)
        self.assertEqual(foreign.json(), [])
        missing = self.client.get(f"/api/v1/institutes/beta/booking/slots/{self.slot.id}/")
        self.assertEqual(missing.status_code, 403)

    def test_non_member_cannot_book(self):
        outsider = User.objects.create_user(username="outsider", password="x")
        self.client.force_authenticate(outsider)
        response = self.client.post(
            "/api/v1/institutes/alpha/booking/appointments/",
            {"slot_id": self.slot.id, "service_type_id": self.service.id},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_provider_sees_only_own_agenda(self):
        book_slot(customer=self.customer, slot_id=self.slot.id, service_type_id=self.service.id)
        self.client.force_authenticate(self.provider_user)
        rows = self.client.get("/api/v1/institutes/alpha/booking/appointments/").json()
        self.assertEqual(len(rows), 1)
        self.client.force_authenticate(self.admin)
        self.assertEqual(len(self.client.get("/api/v1/institutes/alpha/booking/appointments/").json()), 1)

    def test_cancel_inside_window_refunds_and_legacy_ref_still_refunds(self):
        credit_wallet(
            user=self.customer,
            amount=Decimal("100000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="fund-alpha",
            institute=self.a,
        )
        appointment = book_slot(customer=self.customer, slot_id=self.slot.id, service_type_id=self.service.id)
        fired = []
        appointment_confirmed.connect(lambda **kwargs: fired.append(kwargs["appointment"].pk), weak=False)
        confirm_appointment_payment(
            appointment=appointment, payment_ref="wallet", idempotency_key="pay-alpha"
        )
        self.assertEqual(fired, [appointment.pk])
        appointment.starts_at = timezone.now() + timedelta(hours=48)
        appointment.save(update_fields=["starts_at"])
        cancel_appointment(appointment=appointment, canceled_by="patient")
        appointment.refresh_from_db()
        self.assertEqual(appointment.refund_policy_applied, Appointment.RefundPolicy.FULL_REFUND)

        late = Slot.objects.create(
            provider=self.provider,
            starts_at=timezone.now() + timedelta(hours=2),
            ends_at=timezone.now() + timedelta(hours=3),
            status=Slot.Status.OPEN,
            institute=self.a,
        )
        credit_wallet(
            user=self.customer,
            amount=Decimal("100000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="fund-late",
            institute=self.a,
        )
        second = book_slot(customer=self.customer, slot_id=late.id, service_type_id=self.service.id)
        confirm_appointment_payment(
            appointment=second, payment_ref="wallet", idempotency_key="pay-late"
        )
        second.deposit_ledger_ref = second.deposit_ledger_ref
        second.starts_at = timezone.now() + timedelta(hours=2)
        second.save(update_fields=["starts_at"])
        LedgerEntry.objects.filter(reference=f"booking.appointment:{second.pk}").update(
            reference=f"psy.appointment:{second.pk}"
        )
        cancel_appointment(appointment=second, canceled_by="patient")
        second.refresh_from_db()
        self.assertEqual(second.refund_policy_applied, Appointment.RefundPolicy.FORFEIT)
        self.a.settings = {"booking": {"refund_on_late_cancel": True}}
        self.a.save(update_fields=["settings"])
        # A third appointment, late, with the setting on, is refunded.
        credit_wallet(
            user=self.customer,
            amount=Decimal("100000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="fund-setting",
            institute=self.a,
        )
        third_slot = Slot.objects.create(
            provider=self.provider,
            starts_at=timezone.now() + timedelta(hours=4),
            ends_at=timezone.now() + timedelta(hours=5),
            status=Slot.Status.OPEN,
            institute=self.a,
        )
        third = book_slot(customer=self.customer, slot_id=third_slot.id, service_type_id=self.service.id)
        confirm_appointment_payment(
            appointment=third, payment_ref="wallet", idempotency_key="pay-setting"
        )
        third.starts_at = timezone.now() + timedelta(hours=1)
        third.save(update_fields=["starts_at"])
        cancel_appointment(appointment=third, canceled_by="patient")
        third.refresh_from_db()
        self.assertEqual(third.refund_policy_applied, Appointment.RefundPolicy.FULL_REFUND)

    def test_slot_generation_respects_a_day_off(self):
        today = timezone.localdate()
        ProviderAvailability.objects.create(
            provider=self.provider,
            weekday=today.weekday(),
            start_time="09:00",
            end_time="11:00",
            valid_from=today,
            institute=self.a,
        )
        from apps.modules.booking.models import AvailabilityException

        AvailabilityException.objects.create(
            provider=self.provider, date=today, is_day_off=True, institute=self.a
        )
        created = regenerate_slots_for_provider(provider=self.provider, range_start=today, range_end=today)
        self.assertEqual(created, 0)

    def test_review_requires_a_completed_owned_appointment(self):
        booked = book_slot(customer=self.customer, slot_id=self.slot.id, service_type_id=self.service.id)
        self.client.force_authenticate(self.customer)
        denied = self.client.post(
            f"/api/v1/institutes/alpha/booking/appointments/{booked.id}/review/",
            {"rating": 5, "body": "خوب"},
            format="json",
        )
        self.assertEqual(denied.status_code, 400)
        booked.status = Appointment.Status.COMPLETED
        booked.ends_at = timezone.now() - timedelta(hours=1)
        booked.save(update_fields=["status", "ends_at"])
        ok = self.client.post(
            f"/api/v1/institutes/alpha/booking/appointments/{booked.id}/review/",
            {"rating": 5, "body": "خوب"},
            format="json",
        )
        self.assertEqual(ok.status_code, 201, ok.content)
        self.assertTrue(AppointmentReview.objects.filter(appointment=booked).exists())
        again = self.client.post(
            f"/api/v1/institutes/alpha/booking/appointments/{booked.id}/review/",
            {"rating": 4, "body": "دوباره"},
            format="json",
        )
        self.assertEqual(again.status_code, 400)
        hidden = self.client.get(f"/api/v1/institutes/alpha/booking/providers/{self.provider.id}/reviews/")
        self.assertEqual(hidden.json(), [])
        self.client.force_authenticate(self.admin)
        pending = self.client.get("/api/v1/institutes/alpha/reviews/moderation/?status=pending").json()
        self.assertEqual(len(pending), 1)
        approved = self.client.post(
            f"/api/v1/institutes/alpha/reviews/moderation/{pending[0]['id']}/approve/",
            {},
            format="json",
        )
        self.assertEqual(approved.status_code, 200, approved.content)
        self.client.force_authenticate(self.other)
        foreign = self.client.get("/api/v1/institutes/beta/reviews/?target=provider&target_id=%s" % self.provider.id)
        self.assertEqual(foreign.status_code, 404)

    def test_foreign_provider_is_not_found(self):
        self.client.force_authenticate(self.admin)
        missing = self.client.get(f"/api/v1/institutes/beta/booking/providers/{self.provider.id}/")
        self.assertEqual(missing.status_code, 404)

    def test_leave_approval_blocks_the_day_and_keeps_the_appointment(self):
        from datetime import time

        from apps.modules.booking.models import AvailabilityException, LeaveRequest

        day = timezone.localdate() + timedelta(days=4)
        ProviderAvailability.objects.create(
            provider=self.provider,
            weekday=day.weekday(),
            start_time=time(9, 0),
            end_time=time(12, 0),
            valid_from=day,
            institute=self.a,
        )
        start = timezone.make_aware(datetime.combine(day, time(10, 0)))
        open_slot = Slot.objects.create(
            provider=self.provider,
            starts_at=start,
            ends_at=start + timedelta(minutes=45),
            status=Slot.Status.OPEN,
            institute=self.a,
        )
        held = Slot.objects.create(
            provider=self.provider,
            starts_at=start + timedelta(hours=1),
            ends_at=start + timedelta(hours=1, minutes=45),
            status=Slot.Status.BOOKED,
            institute=self.a,
        )
        appointment = Appointment.objects.create(
            slot=held,
            customer=self.customer,
            provider=self.provider,
            service_type=self.service,
            starts_at=held.starts_at,
            ends_at=held.ends_at,
            status=Appointment.Status.CONFIRMED,
            price_snapshot=self.service.price,
            institute=self.a,
        )
        self.client.force_authenticate(self.provider_user)
        created = self.client.post(
            "/api/v1/institutes/alpha/booking/leave-requests/",
            {"starts_on": day.isoformat(), "ends_on": day.isoformat(), "reason": "day off"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        self.client.force_authenticate(self.admin)
        approved = self.client.post(
            f"/api/v1/institutes/alpha/booking/leave-requests/{created.json()['id']}/approve/",
            {"admin_note": "ok"},
            format="json",
        )
        self.assertEqual(approved.status_code, 200, approved.content)
        self.assertEqual(approved.json()["status"], LeaveRequest.Status.APPROVED)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.CONFIRMED)
        self.assertTrue(
            AvailabilityException.objects.filter(provider=self.provider, date=day, is_day_off=True).exists()
        )
        self.assertFalse(Slot.objects.filter(pk=open_slot.pk, status=Slot.Status.OPEN).exists())

    def test_legacy_payment_reference_still_refunds_inside_the_window(self):
        credit_wallet(
            user=self.customer,
            amount=Decimal("100000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="fund-legacy-ref",
            institute=self.a,
        )
        appointment = book_slot(customer=self.customer, slot_id=self.slot.id, service_type_id=self.service.id)
        confirm_appointment_payment(
            appointment=appointment, payment_ref="wallet", idempotency_key="pay-legacy-ref"
        )
        LedgerEntry.objects.filter(reference=f"booking.appointment:{appointment.pk}").update(
            reference=f"psy.appointment:{appointment.pk}"
        )
        appointment.starts_at = timezone.now() + timedelta(hours=48)
        appointment.save(update_fields=["starts_at"])
        cancel_appointment(appointment=appointment, canceled_by="patient")
        appointment.refresh_from_db()
        self.assertEqual(appointment.refund_policy_applied, Appointment.RefundPolicy.FULL_REFUND)
        self.assertTrue(
            LedgerEntry.objects.filter(
                reference=f"booking.appointment:{appointment.pk}",
                entry_type=LedgerEntry.EntryType.REFUND,
            ).exists()
        )

    def test_booked_signal_does_not_sms_another_institute(self):
        from apps.kernel.notifications.models import SmsMessage

        self.customer.phone = "09120000000"
        self.customer.save(update_fields=["phone"])
        self.provider_user.phone = "09120000001"
        self.provider_user.save(update_fields=["phone"])
        book_slot(customer=self.customer, slot_id=self.slot.id, service_type_id=self.service.id)
        self.assertEqual(
            SmsMessage.objects.filter(purpose=SmsMessage.Purpose.APPOINTMENT).count(),
            0,
        )


class BookingParityTests(TestCase):
    def test_psy_and_module_booking_return_the_same_state(self):
        from apps.institutes.psy_institute.models import PatientProfile, TherapistProfile
        from apps.kernel.tenancy.services import grant_psy_role

        psy = Institute.objects.get(slug="psy")
        psy.enabled_modules = list(set(psy.enabled_modules) | {"booking", "reviews"})
        psy.is_active = True
        psy.save(update_fields=["enabled_modules", "is_active"])
        patient_user = User.objects.create_user(
            username="parity_patient", password="x", phone="09120000010"
        )
        therapist_user = User.objects.create_user(
            username="parity_therapist", password="x", phone="09120000011"
        )
        grant_psy_role(patient_user, "member")
        grant_psy_role(therapist_user, "staff")
        patient = PatientProfile.objects.get(user=patient_user)
        therapist = TherapistProfile.objects.create(
            user=therapist_user, display_name="Parity", is_active=True, is_accepting_patients=True
        )
        service = ServiceType.objects.create(
            institute=psy,
            name="Parity",
            slug="parity",
            modality=ServiceType.Modality.ONLINE,
            duration_minutes=45,
            price=Decimal("100000"),
        )
        ProviderServiceOffer.objects.create(
            provider=therapist.provider, service_type=service, institute=psy
        )
        start = timezone.now() + timedelta(days=5)
        first = Slot.objects.create(
            provider=therapist.provider,
            starts_at=start,
            ends_at=start + timedelta(minutes=45),
            status=Slot.Status.OPEN,
            institute=psy,
        )
        second = Slot.objects.create(
            provider=therapist.provider,
            starts_at=start + timedelta(hours=2),
            ends_at=start + timedelta(hours=2, minutes=45),
            status=Slot.Status.OPEN,
            institute=psy,
        )
        client = APIClient()
        client.force_authenticate(patient_user)
        psy_row = client.post(
            "/api/v1/psy/appointments/",
            {"slot_id": first.id, "session_type_id": service.id},
            format="json",
        )
        module_row = client.post(
            "/api/v1/institutes/psy/booking/appointments/",
            {"slot_id": second.id, "service_type_id": service.id},
            format="json",
        )
        self.assertEqual(psy_row.status_code, 201, psy_row.content)
        self.assertEqual(module_row.status_code, 201, module_row.content)
        self.assertEqual(psy_row.json()["status"], module_row.json()["status"])
        self.assertEqual(psy_row.json()["patient"], patient.id)
        self.assertEqual(module_row.json()["patient"], patient.id)
        self.assertEqual(psy_row.json()["therapist"], therapist.id)
        self.assertEqual(module_row.json()["therapist"], therapist.id)
        from apps.kernel.notifications.models import SmsMessage

        self.assertGreaterEqual(
            SmsMessage.objects.filter(purpose=SmsMessage.Purpose.APPOINTMENT).count(),
            4,
        )
