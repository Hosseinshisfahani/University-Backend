"""
Psychology institute tests.

Overlap (GiST) and full booking flows require PostgreSQL.
Ledger/wallet unit tests live in apps.finance.tests (SQLite-safe).
"""

from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.institutes.psy_institute.models import (
    Appointment,
    AppointmentSlot,
    AvailabilityException,
    PatientProfile,
    SessionType,
    TherapistAvailability,
    TherapistProfile,
    TherapistSessionOffer,
    Workshop,
)

User = get_user_model()


class ProfileSmokeTests(TestCase):
    def test_create_profiles_and_groups(self):
        for name in ("psy_admin", "psy_therapist", "psy_patient"):
            Group.objects.get_or_create(name=name)

        therapist_user = User.objects.create_user(username="th1", password="x")
        patient_user = User.objects.create_user(username="pt1", password="x")
        therapist_user.groups.add(Group.objects.get(name="psy_therapist"))
        patient_user.groups.add(Group.objects.get(name="psy_patient"))

        TherapistProfile.objects.create(user=therapist_user, display_name="Dr. A")
        PatientProfile.objects.create(user=patient_user, phone="09120000000")

        self.assertTrue(hasattr(therapist_user, "therapist_profile"))
        self.assertTrue(hasattr(patient_user, "patient_profile"))


class TherapistPortalApiTests(TestCase):
    def setUp(self):
        for name in ("psy_admin", "psy_therapist", "psy_patient"):
            Group.objects.get_or_create(name=name)

        self.therapist_user = User.objects.create_user(
            username="therapist_api", password="Pass1234!"
        )
        self.patient_user = User.objects.create_user(
            username="patient_api", password="Pass1234!", first_name="Ali"
        )
        self.therapist_user.groups.add(Group.objects.get(name="psy_therapist"))
        self.patient_user.groups.add(Group.objects.get(name="psy_patient"))

        self.therapist = TherapistProfile.objects.create(
            user=self.therapist_user, display_name="Dr. Test"
        )
        self.patient = PatientProfile.objects.create(
            user=self.patient_user, phone="09121110000"
        )
        self.session_type = SessionType.objects.create(
            name="Online 45",
            slug="online-45-test",
            modality=SessionType.Modality.ONLINE,
            duration_minutes=45,
            price=Decimal("500000"),
        )
        starts = timezone.now() + timedelta(days=2)
        self.slot = AppointmentSlot.objects.create(
            therapist=self.therapist,
            session_type=self.session_type,
            starts_at=starts,
            ends_at=starts + timedelta(minutes=45),
            status=AppointmentSlot.Status.BOOKED,
        )
        self.appointment = Appointment.objects.create(
            slot=self.slot,
            patient=self.patient,
            therapist=self.therapist,
            session_type=self.session_type,
            starts_at=self.slot.starts_at,
            ends_at=self.slot.ends_at,
            status=Appointment.Status.CONFIRMED,
            price_snapshot=self.session_type.price,
        )
        self.client = APIClient()

    def test_set_meeting_link_as_therapist(self):
        self.client.force_authenticate(self.therapist_user)
        url = reverse(
            "psy_institute:appointment-set-meeting-link",
            kwargs={"pk": self.appointment.pk},
        )
        response = self.client.post(
            url, {"meeting_link": "https://meet.google.com/abc-defg-hij"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["meeting_link"], "https://meet.google.com/abc-defg-hij"
        )
        self.assertEqual(response.json()["session_type_modality"], "online")
        self.appointment.refresh_from_db()
        self.assertEqual(
            self.appointment.meeting_link, "https://meet.google.com/abc-defg-hij"
        )

    def test_set_meeting_link_forbidden_for_patient(self):
        self.client.force_authenticate(self.patient_user)
        url = reverse(
            "psy_institute:appointment-set-meeting-link",
            kwargs={"pk": self.appointment.pk},
        )
        response = self.client.post(
            url, {"meeting_link": "https://meet.google.com/x"}, format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_therapist_patients_list_and_detail(self):
        self.client.force_authenticate(self.therapist_user)
        list_url = reverse("psy_institute:therapist-patient-list")
        list_resp = self.client.get(list_url)
        self.assertEqual(list_resp.status_code, 200)
        body = list_resp.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["id"], self.patient.id)
        self.assertEqual(body[0]["appointments_count"], 1)
        self.assertIn("Ali", body[0]["display_name"])

        detail_url = reverse(
            "psy_institute:therapist-patient-detail", kwargs={"pk": self.patient.pk}
        )
        detail_resp = self.client.get(detail_url)
        self.assertEqual(detail_resp.status_code, 200)
        detail = detail_resp.json()
        self.assertEqual(len(detail["recent_appointments"]), 1)
        self.assertEqual(detail["recent_appointments"][0]["id"], self.appointment.id)


class AdminPortalApiTests(TestCase):
    def setUp(self):
        for name in ("psy_admin", "psy_therapist", "psy_patient"):
            Group.objects.get_or_create(name=name)

        self.admin_user = User.objects.create_user(
            username="admin_api", password="Pass1234!"
        )
        self.admin_user.groups.add(Group.objects.get(name="psy_admin"))

        self.therapist_user = User.objects.create_user(
            username="th_admin", password="Pass1234!"
        )
        self.therapist_user.groups.add(Group.objects.get(name="psy_therapist"))
        self.patient_user = User.objects.create_user(
            username="pt_admin", password="Pass1234!", first_name="Sara"
        )
        self.patient_user.groups.add(Group.objects.get(name="psy_patient"))

        self.therapist = TherapistProfile.objects.create(
            user=self.therapist_user, display_name="Dr. Admin Test"
        )
        self.patient = PatientProfile.objects.create(
            user=self.patient_user, phone="09123334444"
        )
        self.session_type = SessionType.objects.create(
            name="Online 45",
            slug="online-45-admin",
            modality=SessionType.Modality.ONLINE,
            duration_minutes=45,
            price=Decimal("500000"),
        )
        starts = timezone.now() + timedelta(days=3)
        self.slot = AppointmentSlot.objects.create(
            therapist=self.therapist,
            session_type=self.session_type,
            starts_at=starts,
            ends_at=starts + timedelta(minutes=45),
            status=AppointmentSlot.Status.BOOKED,
        )
        self.appointment = Appointment.objects.create(
            slot=self.slot,
            patient=self.patient,
            therapist=self.therapist,
            session_type=self.session_type,
            starts_at=self.slot.starts_at,
            ends_at=self.slot.ends_at,
            status=Appointment.Status.CONFIRMED,
            price_snapshot=self.session_type.price,
        )
        self.client = APIClient()

    def test_admin_directories_and_overview(self):
        self.client.force_authenticate(self.admin_user)
        overview = self.client.get(reverse("psy_institute:admin-overview"))
        self.assertEqual(overview.status_code, 200)
        self.assertGreaterEqual(overview.json()["patients_count"], 1)
        self.assertGreaterEqual(overview.json()["upcoming_confirmed_count"], 1)

        patients = self.client.get(reverse("psy_institute:admin-patient-list"))
        self.assertEqual(patients.status_code, 200)
        self.assertGreaterEqual(patients.json()["count"], 1)
        self.assertIn("wallet_balance", patients.json()["results"][0])

        detail = self.client.get(
            reverse(
                "psy_institute:admin-patient-detail", kwargs={"pk": self.patient.pk}
            )
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["username"], "pt_admin")

        therapists = self.client.get(reverse("psy_institute:admin-therapist-list"))
        self.assertEqual(therapists.status_code, 200)
        self.assertGreaterEqual(therapists.json()["count"], 1)

        finance = self.client.get(reverse("psy_institute:admin-finance-summary"))
        self.assertEqual(finance.status_code, 200)
        self.assertIn("net_appointment_revenue", finance.json())

    def test_appointments_paginated_for_admin(self):
        self.client.force_authenticate(self.admin_user)
        url = reverse("psy_institute:appointment-list")
        resp = self.client.get(url, {"page": 1, "page_size": 10})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("results", body)
        self.assertIn("count", body)
        self.assertTrue(any(r["id"] == self.appointment.id for r in body["results"]))
        self.assertIn("patient_name", body["results"][0])

    def test_regenerate_does_not_delete_slots_tied_to_canceled_appointments(self):
        from apps.institutes.psy_institute.services import (
            cancel_appointment,
            regenerate_slots_for_therapist,
        )

        self.appointment.status = Appointment.Status.PENDING_PAYMENT
        self.appointment.save(update_fields=["status", "updated_at"])
        cancel_appointment(appointment=self.appointment, canceled_by="admin")
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.status, AppointmentSlot.Status.BLOCKED)

        # Simulate the previous bug: a canceled appointment still attached
        # to an OPEN slot that regenerate would try to delete.
        self.slot.status = AppointmentSlot.Status.OPEN
        self.slot.save(update_fields=["status", "updated_at"])

        day = timezone.localdate(self.slot.starts_at)
        created = regenerate_slots_for_therapist(
            therapist=self.therapist,
            range_start=day,
            range_end=day,
        )
        self.assertGreaterEqual(created, 0)
        self.slot.refresh_from_db()
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.slot_id, self.slot.id)
        self.assertEqual(self.slot.status, AppointmentSlot.Status.BLOCKED)

    def test_admin_endpoints_forbidden_for_patient(self):
        self.client.force_authenticate(self.patient_user)
        resp = self.client.get(reverse("psy_institute:admin-overview"))
        self.assertEqual(resp.status_code, 403)


class WorkshopEnrollmentFlowTests(TestCase):
    def setUp(self):
        for name in ("psy_admin", "psy_therapist", "psy_patient"):
            Group.objects.get_or_create(name=name)

        self.admin = User.objects.create_user(username="ws_admin", password="x")
        self.admin.groups.add(Group.objects.get(name="psy_admin"))
        self.therapist_user = User.objects.create_user(username="ws_th", password="x")
        self.therapist_user.groups.add(Group.objects.get(name="psy_therapist"))
        self.patient_user = User.objects.create_user(username="ws_pt", password="x")
        self.patient_user.groups.add(Group.objects.get(name="psy_patient"))

        self.therapist = TherapistProfile.objects.create(
            user=self.therapist_user, display_name="Dr WS"
        )
        self.patient = PatientProfile.objects.create(
            user=self.patient_user, phone="09120001111"
        )
        self.workshop = Workshop.objects.create(
            title="Paid WS",
            slug="paid-ws",
            description="test",
            instructor=self.therapist,
            capacity=2,
            price=Decimal("100000"),
            starts_at=timezone.now() + timedelta(days=5),
            ends_at=timezone.now() + timedelta(days=5, hours=2),
            is_published=True,
        )
        self.free = Workshop.objects.create(
            title="Free WS",
            slug="free-ws",
            instructor=self.therapist,
            capacity=10,
            price=Decimal("0"),
            starts_at=timezone.now() + timedelta(days=3),
            is_published=True,
        )
        from apps.finance import services as finance_services
        from apps.finance.models import LedgerEntry

        finance_services.credit_wallet(
            user=self.patient_user,
            amount=Decimal("500000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="ws-test-deposit",
        )
        self.client = APIClient()

    def test_free_enroll_activates_immediately(self):
        self.client.force_authenticate(self.patient_user)
        url = reverse("psy_institute:workshop-enroll", kwargs={"slug": "free-ws"})
        resp = self.client.post(url, {}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["status"], "active")

    def test_paid_hold_then_confirm(self):
        self.client.force_authenticate(self.patient_user)
        enroll_url = reverse(
            "psy_institute:workshop-enroll", kwargs={"slug": "paid-ws"}
        )
        hold = self.client.post(enroll_url, {}, format="json")
        self.assertEqual(hold.status_code, 201)
        body = hold.json()
        self.assertEqual(body["status"], "pending_payment")
        self.assertEqual(body["price_snapshot"], "100000")
        self.assertIsNotNone(body["hold_expires_at"])

        confirm_url = reverse(
            "psy_institute:workshop-confirm-enrollment",
            kwargs={"slug": "paid-ws", "enrollment_id": body["id"]},
        )
        confirm = self.client.post(
            confirm_url,
            {"payment_ref": "wallet", "idempotency_key": "ws-c1"},
            format="json",
        )
        self.assertEqual(confirm.status_code, 200)
        self.assertEqual(confirm.json()["status"], "active")

    def test_admin_force_cancel_refunds(self):
        self.client.force_authenticate(self.patient_user)
        enroll = self.client.post(
            reverse("psy_institute:workshop-enroll", kwargs={"slug": "paid-ws"}),
            {},
            format="json",
        ).json()
        self.client.post(
            reverse(
                "psy_institute:workshop-confirm-enrollment",
                kwargs={"slug": "paid-ws", "enrollment_id": enroll["id"]},
            ),
            {"payment_ref": "wallet", "idempotency_key": "ws-c2"},
            format="json",
        )
        self.client.force_authenticate(self.admin)
        cancel = self.client.post(
            reverse(
                "psy_institute:workshop-cancel-enrollment",
                kwargs={"slug": "paid-ws", "enrollment_id": enroll["id"]},
            ),
            {"reason": "admin cancel"},
            format="json",
        )
        self.assertEqual(cancel.status_code, 200)
        self.assertEqual(cancel.json()["status"], "refunded")


class WorkshopLmsGatingTests(TestCase):
    def setUp(self):
        for name in ("psy_admin", "psy_therapist", "psy_patient"):
            Group.objects.get_or_create(name=name)

        self.patient_user = User.objects.create_user(username="lms_pt", password="x")
        self.patient_user.groups.add(Group.objects.get(name="psy_patient"))
        self.other_user = User.objects.create_user(username="lms_pt2", password="x")
        self.other_user.groups.add(Group.objects.get(name="psy_patient"))
        self.therapist_user = User.objects.create_user(username="lms_th", password="x")
        self.therapist_user.groups.add(Group.objects.get(name="psy_therapist"))

        self.therapist = TherapistProfile.objects.create(
            user=self.therapist_user, display_name="Dr LMS"
        )
        self.patient = PatientProfile.objects.create(
            user=self.patient_user, phone="09120002222"
        )
        PatientProfile.objects.create(user=self.other_user, phone="09120003333")

        self.workshop = Workshop.objects.create(
            title="LMS WS",
            slug="lms-ws",
            description="short",
            body_md="## Intro\n\nHello",
            instructor=self.therapist,
            capacity=10,
            price=Decimal("0"),
            starts_at=timezone.now() + timedelta(days=2),
            is_published=True,
            certificate_enabled=True,
        )
        from apps.institutes.psy_institute.models import (
            WorkshopEnrollment,
            WorkshopResource,
            WorkshopSession,
        )

        self.session1 = WorkshopSession.objects.create(
            workshop=self.workshop,
            sort_order=1,
            title="S1",
            summary="first",
            meeting_url="https://meet.example.com/s1",
        )
        self.session2 = WorkshopSession.objects.create(
            workshop=self.workshop,
            sort_order=2,
            title="S2",
            summary="second",
            recording_url="https://cdn.example.com/s2.mp4",
        )
        WorkshopResource.objects.create(
            workshop=self.workshop,
            session=self.session1,
            sort_order=1,
            title="Slides",
            kind=WorkshopResource.Kind.SLIDES,
            file_url="https://cdn.example.com/s1.pdf",
        )
        WorkshopResource.objects.create(
            workshop=self.workshop,
            session=None,
            sort_order=1,
            title="Workbook",
            kind=WorkshopResource.Kind.PDF,
            file_url="https://cdn.example.com/workbook.pdf",
        )
        self.enrollment = WorkshopEnrollment.objects.create(
            workshop=self.workshop,
            patient=self.patient,
            status=WorkshopEnrollment.Status.ACTIVE,
            price_snapshot=Decimal("0"),
            payment_ref="free",
        )
        self.client = APIClient()

    def test_anonymous_detail_redacts_urls(self):
        url = reverse("psy_institute:workshop-detail", kwargs={"slug": "lms-ws"})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["viewer_has_access"])
        self.assertIsNone(body["progress_percent"])
        self.assertEqual(len(body["sessions"]), 2)
        s1 = body["sessions"][0]
        self.assertTrue(s1["has_meeting"])
        self.assertIsNone(s1["meeting_url"])
        self.assertTrue(s1["is_locked"])
        self.assertTrue(s1["resources"][0]["has_file"])
        self.assertIsNone(s1["resources"][0]["file_url"])
        self.assertTrue(body["resources"][0]["is_locked"])
        self.assertIsNone(body["resources"][0]["file_url"])

    def test_active_patient_sees_urls(self):
        self.client.force_authenticate(self.patient_user)
        url = reverse("psy_institute:workshop-detail", kwargs={"slug": "lms-ws"})
        body = self.client.get(url).json()
        self.assertTrue(body["viewer_has_access"])
        self.assertEqual(body["progress_percent"], 0)
        s1 = body["sessions"][0]
        self.assertEqual(s1["meeting_url"], "https://meet.example.com/s1")
        self.assertFalse(s1["is_locked"])
        self.assertEqual(
            s1["resources"][0]["file_url"], "https://cdn.example.com/s1.pdf"
        )
        self.assertEqual(
            body["resources"][0]["file_url"], "https://cdn.example.com/workbook.pdf"
        )

    def test_complete_all_and_issue_certificate(self):
        self.client.force_authenticate(self.patient_user)
        for session in (self.session1, self.session2):
            complete_url = reverse(
                "psy_institute:workshop-complete-session",
                kwargs={"slug": "lms-ws", "session_id": session.pk},
            )
            resp = self.client.post(complete_url, {}, format="json")
            self.assertEqual(resp.status_code, 200)
        detail = self.client.get(
            reverse("psy_institute:workshop-detail", kwargs={"slug": "lms-ws"})
        ).json()
        self.assertEqual(detail["progress_percent"], 100)

        issue_url = reverse(
            "psy_institute:workshop-issue-certificate", kwargs={"slug": "lms-ws"}
        )
        issued = self.client.post(issue_url, {}, format="json")
        self.assertEqual(issued.status_code, 201)
        self.assertIn("certificate_code", issued.json())

        detail2 = self.client.get(
            reverse("psy_institute:workshop-detail", kwargs={"slug": "lms-ws"})
        ).json()
        self.assertIsNotNone(detail2["certificate"])

    def test_non_enrolled_cannot_complete(self):
        self.client.force_authenticate(self.other_user)
        url = reverse(
            "psy_institute:workshop-complete-session",
            kwargs={"slug": "lms-ws", "session_id": self.session1.pk},
        )
        resp = self.client.post(url, {}, format="json")
        self.assertEqual(resp.status_code, 403)


class BlogPostApiTests(TestCase):
    def setUp(self):
        for name in ("psy_admin", "psy_therapist", "psy_patient"):
            Group.objects.get_or_create(name=name)

        self.admin = User.objects.create_user(username="blog_admin", password="x")
        self.admin.groups.add(Group.objects.get(name="psy_admin"))
        self.admin.is_staff = True
        self.admin.save()

        self.therapist_user = User.objects.create_user(
            username="blog_th", password="x", first_name="سارا", last_name="احمدی"
        )
        self.therapist_user.groups.add(Group.objects.get(name="psy_therapist"))
        self.therapist = TherapistProfile.objects.create(
            user=self.therapist_user, display_name="سارا احمدی"
        )

        from apps.institutes.psy_institute.models import BlogPost

        self.published = BlogPost.objects.create(
            title="Published Post",
            slug="published-post",
            excerpt="ex",
            body="## Hello\n\nWorld",
            is_published=True,
            published_at=timezone.now(),
            author=self.therapist_user,
        )
        self.draft = BlogPost.objects.create(
            title="Draft Post",
            slug="draft-post",
            body="secret",
            is_published=False,
            author=self.admin,
        )
        self.client = APIClient()

    def test_anonymous_list_hides_drafts_and_paginates(self):
        url = reverse("psy_institute:blog-list")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("results", body)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["slug"], "published-post")
        self.assertEqual(body["results"][0]["author_name"], "سارا احمدی")
        self.assertEqual(
            body["results"][0]["author_therapist_id"], self.therapist.id
        )

    def test_anonymous_cannot_retrieve_draft(self):
        url = reverse("psy_institute:blog-detail", kwargs={"slug": "draft-post"})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_admin_create_stamps_published_at(self):
        self.client.force_authenticate(self.admin)
        url = reverse("psy_institute:blog-list")
        resp = self.client.post(
            url,
            {
                "title": "New Pub",
                "slug": "new-pub",
                "body": "body",
                "is_published": True,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data["is_published"])
        self.assertIsNotNone(data["published_at"])
        self.assertEqual(data["author_name"], "blog_admin")


class AdminCentricSchedulingTests(TestCase):
    def setUp(self):
        for name in ("psy_admin", "psy_therapist", "psy_patient"):
            Group.objects.get_or_create(name=name)

        self.admin_user = User.objects.create_user(
            username="sched_admin", password="Pass1234!"
        )
        self.admin_user.groups.add(Group.objects.get(name="psy_admin"))
        self.therapist_user = User.objects.create_user(
            username="sched_th", password="Pass1234!"
        )
        self.therapist_user.groups.add(Group.objects.get(name="psy_therapist"))
        self.patient_user = User.objects.create_user(
            username="sched_pt", password="Pass1234!", first_name="Neda"
        )
        self.patient_user.groups.add(Group.objects.get(name="psy_patient"))

        self.therapist = TherapistProfile.objects.create(
            user=self.therapist_user, display_name="Dr Schedule"
        )
        self.patient = PatientProfile.objects.create(
            user=self.patient_user, phone="09125550000"
        )
        self.session_type = SessionType.objects.create(
            name="Online 45",
            slug="online-45-sched",
            modality=SessionType.Modality.ONLINE,
            duration_minutes=45,
            price=Decimal("200000"),
        )
        TherapistSessionOffer.objects.create(
            therapist=self.therapist, session_type=self.session_type
        )
        self.starts = timezone.now() + timedelta(days=4)
        self.open_slot = AppointmentSlot.objects.create(
            therapist=self.therapist,
            session_type=None,
            starts_at=self.starts,
            ends_at=self.starts + timedelta(minutes=45),
            status=AppointmentSlot.Status.OPEN,
        )
        self.client = APIClient()

    def test_therapist_cannot_write_availability(self):
        self.client.force_authenticate(self.therapist_user)
        url = reverse("psy_institute:therapist-availability-list")
        resp = self.client.post(
            url,
            {
                "weekday": 0,
                "start_time": "09:00",
                "end_time": "12:00",
                "valid_from": timezone.localdate().isoformat(),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_therapist_cannot_cancel_appointment(self):
        slot = AppointmentSlot.objects.create(
            therapist=self.therapist,
            session_type=self.session_type,
            starts_at=self.starts + timedelta(hours=2),
            ends_at=self.starts + timedelta(hours=2, minutes=45),
            status=AppointmentSlot.Status.BOOKED,
        )
        appt = Appointment.objects.create(
            slot=slot,
            patient=self.patient,
            therapist=self.therapist,
            session_type=self.session_type,
            starts_at=slot.starts_at,
            ends_at=slot.ends_at,
            status=Appointment.Status.CONFIRMED,
            price_snapshot=self.session_type.price,
        )
        self.client.force_authenticate(self.therapist_user)
        resp = self.client.post(
            reverse("psy_institute:appointment-cancel", kwargs={"pk": appt.pk}),
            {"reason": "x"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_admin_create_overlapping_slot_conflict(self):
        self.client.force_authenticate(self.admin_user)
        url = reverse("psy_institute:admin-slot-list")
        resp = self.client.post(
            url,
            {
                "therapist_id": self.therapist.id,
                "starts_at": self.open_slot.starts_at.isoformat(),
                "ends_at": self.open_slot.ends_at.isoformat(),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 409)

    def test_admin_delete_booked_slot_conflict(self):
        self.open_slot.status = AppointmentSlot.Status.BOOKED
        self.open_slot.save(update_fields=["status"])
        Appointment.objects.create(
            slot=self.open_slot,
            patient=self.patient,
            therapist=self.therapist,
            session_type=self.session_type,
            starts_at=self.open_slot.starts_at,
            ends_at=self.open_slot.ends_at,
            status=Appointment.Status.CONFIRMED,
            price_snapshot=self.session_type.price,
        )
        self.client.force_authenticate(self.admin_user)
        resp = self.client.delete(
            reverse(
                "psy_institute:admin-slot-detail", kwargs={"pk": self.open_slot.pk}
            )
        )
        self.assertEqual(resp.status_code, 409)

    def test_admin_book_pending_wallet_and_offline(self):
        from apps.finance import services as finance_services
        from apps.finance.models import LedgerEntry, Wallet

        wallet_slot = AppointmentSlot.objects.create(
            therapist=self.therapist,
            session_type=None,
            starts_at=self.starts + timedelta(hours=3),
            ends_at=self.starts + timedelta(hours=3, minutes=45),
            status=AppointmentSlot.Status.OPEN,
        )
        offline_slot = AppointmentSlot.objects.create(
            therapist=self.therapist,
            session_type=None,
            starts_at=self.starts + timedelta(hours=4),
            ends_at=self.starts + timedelta(hours=4, minutes=45),
            status=AppointmentSlot.Status.OPEN,
        )
        finance_services.credit_wallet(
            user=self.patient_user,
            amount=Decimal("500000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="sched-deposit",
        )
        wallet = Wallet.objects.get(user=self.patient_user)
        before = wallet.balance

        self.client.force_authenticate(self.admin_user)
        create_url = reverse("psy_institute:admin-appointment-create")

        pending = self.client.post(
            create_url,
            {
                "patient_id": self.patient.id,
                "slot_id": self.open_slot.id,
                "session_type_id": self.session_type.id,
                "payment": "pending",
            },
            format="json",
        )
        self.assertEqual(pending.status_code, 201)
        self.assertEqual(pending.json()["status"], "pending_payment")

        paid = self.client.post(
            create_url,
            {
                "patient_id": self.patient.id,
                "slot_id": wallet_slot.id,
                "session_type_id": self.session_type.id,
                "payment": "wallet",
            },
            format="json",
        )
        self.assertEqual(paid.status_code, 201)
        self.assertEqual(paid.json()["status"], "confirmed")
        self.assertEqual(paid.json()["payment_ref"], "wallet")
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, before - Decimal("200000"))

        offline = self.client.post(
            create_url,
            {
                "patient_id": self.patient.id,
                "slot_id": offline_slot.id,
                "session_type_id": self.session_type.id,
                "payment": "offline",
            },
            format="json",
        )
        self.assertEqual(offline.status_code, 201)
        self.assertEqual(offline.json()["status"], "confirmed")
        self.assertEqual(offline.json()["payment_ref"], "offline")
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, before - Decimal("200000"))

    def test_patient_book_confirm_cancel_still_works(self):
        from apps.finance import services as finance_services
        from apps.finance.models import LedgerEntry, Wallet

        finance_services.credit_wallet(
            user=self.patient_user,
            amount=Decimal("500000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="sched-patient-deposit",
        )
        self.client.force_authenticate(self.patient_user)
        booked = self.client.post(
            reverse("psy_institute:appointment-list"),
            {
                "slot_id": self.open_slot.id,
                "session_type_id": self.session_type.id,
            },
            format="json",
        )
        self.assertEqual(booked.status_code, 201)
        appt_id = booked.json()["id"]
        confirm = self.client.post(
            reverse(
                "psy_institute:appointment-confirm-payment", kwargs={"pk": appt_id}
            ),
            {"payment_ref": "wallet", "idempotency_key": "sched-pay-1"},
            format="json",
        )
        self.assertEqual(confirm.status_code, 200)
        self.assertEqual(confirm.json()["status"], "confirmed")
        canceled = self.client.post(
            reverse("psy_institute:appointment-cancel", kwargs={"pk": appt_id}),
            {"reason": "change"},
            format="json",
        )
        self.assertEqual(canceled.status_code, 200)
        self.assertEqual(canceled.json()["status"], "canceled_by_patient")
        wallet = Wallet.objects.get(user=self.patient_user)
        self.assertEqual(wallet.balance, Decimal("500000"))

    def test_leave_approve_blocks_open_slots_and_returns_conflicts(self):
        day = timezone.localdate(self.starts)
        TherapistAvailability.objects.create(
            therapist=self.therapist,
            weekday=day.weekday(),
            start_time=timezone.localtime(self.starts).time().replace(
                hour=9, minute=0, second=0, microsecond=0
            ),
            end_time=timezone.localtime(self.starts).time().replace(
                hour=18, minute=0, second=0, microsecond=0
            ),
            valid_from=day,
            is_active=True,
        )
        booked_slot = AppointmentSlot.objects.create(
            therapist=self.therapist,
            session_type=self.session_type,
            starts_at=self.starts + timedelta(hours=1),
            ends_at=self.starts + timedelta(hours=1, minutes=45),
            status=AppointmentSlot.Status.BOOKED,
        )
        conflict = Appointment.objects.create(
            slot=booked_slot,
            patient=self.patient,
            therapist=self.therapist,
            session_type=self.session_type,
            starts_at=booked_slot.starts_at,
            ends_at=booked_slot.ends_at,
            status=Appointment.Status.CONFIRMED,
            price_snapshot=self.session_type.price,
        )

        self.client.force_authenticate(self.therapist_user)
        created = self.client.post(
            reverse("psy_institute:therapist-leave-request-list"),
            {
                "starts_on": day.isoformat(),
                "ends_on": day.isoformat(),
                "reason": "مرخصی تست",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        leave_id = created.json()["id"]

        cancel_pending = self.client.post(
            reverse(
                "psy_institute:therapist-leave-request-cancel",
                kwargs={"pk": leave_id},
            ),
            {},
            format="json",
        )
        self.assertEqual(cancel_pending.status_code, 200)
        self.assertEqual(cancel_pending.json()["status"], "canceled")

        created2 = self.client.post(
            reverse("psy_institute:therapist-leave-request-list"),
            {
                "starts_on": day.isoformat(),
                "ends_on": day.isoformat(),
                "reason": "مرخصی تست ۲",
            },
            format="json",
        )
        leave_id = created2.json()["id"]

        self.client.force_authenticate(self.admin_user)
        approved = self.client.post(
            reverse(
                "psy_institute:admin-leave-request-approve", kwargs={"pk": leave_id}
            ),
            {"admin_note": "ok"},
            format="json",
        )
        self.assertEqual(approved.status_code, 200)
        body = approved.json()
        self.assertEqual(body["leave_request"]["status"], "approved")
        conflict_ids = [c["id"] for c in body["conflicts"]]
        self.assertIn(conflict.id, conflict_ids)
        conflict.refresh_from_db()
        self.assertEqual(conflict.status, Appointment.Status.CONFIRMED)
        self.assertTrue(
            AvailabilityException.objects.filter(
                therapist=self.therapist, date=day, is_day_off=True
            ).exists()
        )
        self.assertFalse(
            AppointmentSlot.objects.filter(
                pk=self.open_slot.pk, status=AppointmentSlot.Status.OPEN
            ).exists()
        )

        self.client.force_authenticate(self.therapist_user)
        late_cancel = self.client.post(
            reverse(
                "psy_institute:therapist-leave-request-cancel",
                kwargs={"pk": leave_id},
            ),
            {},
            format="json",
        )
        self.assertEqual(late_cancel.status_code, 400)

    def test_regenerate_creates_generic_open_slots(self):
        from apps.institutes.psy_institute.services import regenerate_slots_for_therapist

        day = timezone.localdate() + timedelta(days=8)
        TherapistAvailability.objects.create(
            therapist=self.therapist,
            weekday=day.weekday(),
            start_time=time(9, 0),
            end_time=time(10, 30),
            valid_from=day,
            is_active=True,
        )
        created = regenerate_slots_for_therapist(
            therapist=self.therapist,
            range_start=day,
            range_end=day,
        )
        self.assertGreater(created, 0)
        slots = AppointmentSlot.objects.filter(
            therapist=self.therapist,
            status=AppointmentSlot.Status.OPEN,
            starts_at__date=day,
        )
        self.assertTrue(slots.exists())
        self.assertTrue(all(slot.session_type_id is None for slot in slots))

    def test_patient_book_requires_offered_session_type(self):
        other_type = SessionType.objects.create(
            name="Clinical 60",
            slug="clinical-60-sched",
            modality=SessionType.Modality.IN_PERSON,
            duration_minutes=60,
            price=Decimal("300000"),
        )
        self.client.force_authenticate(self.patient_user)
        missing = self.client.post(
            reverse("psy_institute:appointment-list"),
            {"slot_id": self.open_slot.id},
            format="json",
        )
        self.assertEqual(missing.status_code, 400)

        unoffered = self.client.post(
            reverse("psy_institute:appointment-list"),
            {
                "slot_id": self.open_slot.id,
                "session_type_id": other_type.id,
            },
            format="json",
        )
        self.assertEqual(unoffered.status_code, 400)

        TherapistSessionOffer.objects.create(
            therapist=self.therapist, session_type=other_type
        )
        too_long = self.client.post(
            reverse("psy_institute:appointment-list"),
            {
                "slot_id": self.open_slot.id,
                "session_type_id": other_type.id,
            },
            format="json",
        )
        self.assertEqual(too_long.status_code, 400)

        therapists = self.client.get(reverse("psy_institute:therapist-list"))
        self.assertEqual(therapists.status_code, 200)
        mine = next(t for t in therapists.json() if t["id"] == self.therapist.id)
        offer_ids = {row["session_type"]["id"] for row in mine["offers"]}
        self.assertIn(self.session_type.id, offer_ids)

        slots = self.client.get(
            reverse(
                "psy_institute:therapist-slots",
                kwargs={"pk": self.therapist.id},
            )
        )
        self.assertEqual(slots.status_code, 200)
        open_row = next(s for s in slots.json() if s["id"] == self.open_slot.id)
        self.assertIsNone(open_row["session_type"])

    def test_admin_availability_crud(self):
        self.client.force_authenticate(self.admin_user)
        url = reverse(
            "psy_institute:admin-therapist-availability-list",
            kwargs={"therapist_id": self.therapist.id},
        )
        created = self.client.post(
            url,
            {
                "weekday": 5,
                "start_time": "09:00",
                "end_time": "13:00",
                "valid_from": timezone.localdate().isoformat(),
                "timezone": "Asia/Tehran",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        monday = self.client.post(
            url,
            {
                "weekday": 0,
                "start_time": "09:00",
                "end_time": "12:00",
                "valid_from": timezone.localdate().isoformat(),
                "timezone": "Asia/Tehran",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(monday.status_code, 201)
        listed = self.client.get(url)
        self.assertEqual(listed.status_code, 200)
        weekdays = [row["weekday"] for row in listed.json()]
        self.assertEqual(weekdays, [5, 0])
        dup = self.client.post(
            url,
            {
                "weekday": 5,
                "start_time": "15:00",
                "end_time": "18:00",
                "valid_from": timezone.localdate().isoformat(),
                "timezone": "Asia/Tehran",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(dup.status_code, 400)

