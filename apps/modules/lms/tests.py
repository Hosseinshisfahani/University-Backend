from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.institutes.psy_institute.models import PatientProfile, TherapistProfile
from apps.kernel.finance.models import LedgerEntry
from apps.kernel.finance.services import credit_wallet, get_or_create_wallet
from apps.kernel.tenancy.models import Institute
from apps.kernel.tenancy.services import grant_roles
from apps.modules.lms.models import Course, CourseSession

User = get_user_model()


class CourseModuleTests(TestCase):
    def setUp(self):
        self.psy = Institute.objects.get(slug="psy")
        self.family = Institute.objects.create(
            slug="family",
            name="خانواده",
            is_active=True,
            enabled_modules=["lms"],
        )
        self.legal = Institute.objects.create(
            slug="legal",
            name="حقوقی",
            is_active=True,
            enabled_modules=["lms"],
        )
        self.admin = User.objects.create_user(username="course_admin", password="x")
        grant_roles(user=self.admin, institute=self.family, roles=["admin"])
        grant_roles(user=self.admin, institute=self.legal, roles=["admin"])
        self.outsider = User.objects.create_user(username="course_outsider", password="x")
        grant_roles(user=self.outsider, institute=self.legal, roles=["admin"])
        self.staff = User.objects.create_user(username="course_staff", first_name="مدرس", last_name="خانواده", password="x")
        grant_roles(user=self.staff, institute=self.family, roles=["staff"])
        self.other_staff = User.objects.create_user(username="course_other_staff", password="x")
        grant_roles(user=self.other_staff, institute=self.family, roles=["staff"])
        self.member = User.objects.create_user(
            username="course_member",
            password="x",
            first_name="نوآموز",
            last_name="خانواده",
        )
        grant_roles(user=self.member, institute=self.family, roles=["member"])
        self.psy_member = User.objects.create_user(
            username="course_psy_member",
            password="x",
            first_name="نوآموز",
            last_name="روان",
        )
        grant_roles(user=self.psy_member, institute=self.psy, roles=["member"])
        self.therapist = User.objects.create_user(username="course_therapist", password="x")
        grant_roles(user=self.therapist, institute=self.psy, roles=["staff"])
        TherapistProfile.objects.create(
            user=self.therapist,
            institute=self.psy,
            display_name="دکتر آزمون",
        )
        self.family_course = Course.objects.create(
            institute=self.family,
            title="دوره خانواده",
            slug="shared-course",
            instructor=self.staff,
            capacity=10,
            price=Decimal("0"),
            is_published=True,
            certificate_enabled=True,
        )
        self.other_course = Course.objects.create(
            institute=self.family,
            title="دوره دیگر",
            slug="other-course",
            instructor=self.other_staff,
            capacity=10,
            price=Decimal("0"),
            is_published=True,
        )
        self.psy_course = Course.objects.create(
            institute=self.psy,
            title="دوره روان",
            slug="shared-course",
            instructor=self.therapist,
            capacity=10,
            price=Decimal("0"),
            is_published=True,
            certificate_enabled=True,
        )
        self.client = APIClient()

    def test_same_slug_roster_and_enrollment_stay_inside_the_institute(self):
        family = self.client.get("/api/v1/institutes/family/lms/courses/shared-course/")
        psy = self.client.get("/api/v1/institutes/psy/lms/courses/shared-course/")
        self.assertEqual(family.json()["title"], "دوره خانواده")
        self.assertEqual(psy.json()["title"], "دوره روان")
        self.assertNotIn("instructor_id", family.json())
        self.assertIn("instructor_id", psy.json())

        self.client.force_authenticate(self.member)
        enrolled = self.client.post("/api/v1/institutes/family/lms/courses/shared-course/enroll/")
        self.assertEqual(enrolled.status_code, 201, enrolled.content)
        enrollment_id = enrolled.json()["id"]
        self.client.force_authenticate(self.admin)
        roster = self.client.get("/api/v1/institutes/family/lms/courses/shared-course/roster/")
        foreign = self.client.get("/api/v1/institutes/legal/lms/courses/shared-course/roster/")
        self.assertEqual(roster.status_code, 200)
        self.assertEqual([row["id"] for row in roster.json()], [enrollment_id])
        self.assertEqual(foreign.status_code, 404)
        grant_roles(user=self.member, institute=self.psy, roles=["member"])
        self.client.force_authenticate(self.member)
        listed = self.client.get("/api/v1/institutes/family/lms/enrollments/")
        hidden = self.client.get("/api/v1/institutes/psy/lms/enrollments/")
        self.assertEqual([row["id"] for row in listed.json()], [enrollment_id])
        self.assertEqual(hidden.status_code, 200)
        self.assertNotIn(enrollment_id, [row["id"] for row in hidden.json()])

    def test_staff_sees_only_the_roster_of_their_own_course(self):
        self.client.force_authenticate(self.member)
        self.client.post("/api/v1/institutes/family/lms/courses/shared-course/enroll/")
        self.client.force_authenticate(self.staff)
        own = self.client.get("/api/v1/institutes/family/lms/courses/shared-course/roster/")
        other = self.client.get("/api/v1/institutes/family/lms/courses/other-course/roster/")
        self.assertEqual(own.status_code, 200)
        self.assertEqual(other.status_code, 403)

    def test_institute_admin_can_publish_without_a_psychology_role(self):
        self.assertFalse(PatientProfile.objects.filter(user=self.member).exists())
        self.client.force_authenticate(self.outsider)
        denied = self.client.post(
            "/api/v1/institutes/family/lms/courses/",
            {
                "title": "ممنوع",
                "slug": "blocked",
                "capacity": 5,
                "price": "0",
                "instructor_user_id": self.staff.id,
            },
            format="json",
        )
        self.assertEqual(denied.status_code, 403)
        self.client.force_authenticate(self.admin)
        created = self.client.post(
            "/api/v1/institutes/family/lms/courses/",
            {
                "title": "منتشر",
                "slug": "published",
                "capacity": 5,
                "price": "0",
                "is_published": True,
                "starts_at": "2030-01-01T09:00:00Z",
                "instructor_user_id": self.staff.id,
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        self.client.force_authenticate(self.member)
        enrolled = self.client.post("/api/v1/institutes/family/lms/courses/published/enroll/")
        self.assertEqual(enrolled.status_code, 201, enrolled.content)
        self.assertEqual(enrolled.json()["status"], "active")
        self.assertEqual(enrolled.json()["user_name"], "نوآموز خانواده")
        self.assertNotIn("patient_name", enrolled.json())
        self.assertNotIn("workshop_title", enrolled.json())

    def test_wallet_confirm_and_refund_window(self):
        soon = Course.objects.create(
            institute=self.family,
            title="نزدیک",
            slug="soon-course",
            instructor=self.staff,
            capacity=10,
            price=Decimal("10000"),
            starts_at=timezone.now() + timedelta(hours=1),
            is_published=True,
        )
        later = Course.objects.create(
            institute=self.family,
            title="دور",
            slug="later-course",
            instructor=self.staff,
            capacity=10,
            price=Decimal("10000"),
            starts_at=timezone.now() + timedelta(hours=48),
            is_published=True,
        )
        credit_wallet(
            user=self.member,
            amount=Decimal("20000"),
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key="course-wallet",
            institute=self.family,
        )
        self.client.force_authenticate(self.member)
        soon_row = self.client.post(f"/api/v1/institutes/family/lms/courses/{soon.slug}/enroll/")
        later_row = self.client.post(f"/api/v1/institutes/family/lms/courses/{later.slug}/enroll/")
        for row, key in ((soon_row, "soon"), (later_row, "later")):
            confirmed = self.client.post(
                f"/api/v1/institutes/family/lms/courses/{row.json()['course_slug']}/enrollments/{row.json()['id']}/confirm/",
                {"payment_ref": "wallet", "idempotency_key": key},
                format="json",
            )
            self.assertEqual(confirmed.status_code, 200, confirmed.content)
        self.assertEqual(get_or_create_wallet(self.member).balance, Decimal("0"))

        kept = self.client.post(
            f"/api/v1/institutes/family/lms/courses/{soon.slug}/enrollments/{soon_row.json()['id']}/cancel/",
            {"reason": "دیر شده"},
            format="json",
        )
        refunded = self.client.post(
            f"/api/v1/institutes/family/lms/courses/{later.slug}/enrollments/{later_row.json()['id']}/cancel/",
            {"reason": "زود"},
            format="json",
        )
        self.assertEqual(kept.json()["status"], "canceled")
        self.assertEqual(refunded.json()["status"], "refunded")
        again = self.client.post(
            f"/api/v1/institutes/family/lms/courses/{later.slug}/enrollments/{later_row.json()['id']}/cancel/",
            {"reason": "دوباره"},
            format="json",
        )
        self.assertEqual(again.status_code, 400)
        self.assertEqual(get_or_create_wallet(self.member).balance, Decimal("10000"))

    def test_certificate_prefix_follows_the_institute(self):
        CourseSession.objects.create(
            institute=self.family,
            workshop=self.family_course,
            title="جلسه",
            sort_order=1,
        )
        CourseSession.objects.create(
            institute=self.psy,
            workshop=self.psy_course,
            title="جلسه",
            sort_order=1,
        )
        self.client.force_authenticate(self.member)
        family = self.client.post("/api/v1/institutes/family/lms/courses/shared-course/enroll/")
        session_id = self.family_course.sessions.get().id
        self.client.post(
            f"/api/v1/institutes/family/lms/courses/shared-course/sessions/{session_id}/complete/"
        )
        certificate = self.client.post(
            "/api/v1/institutes/family/lms/courses/shared-course/certificate/issue/"
        )
        self.assertEqual(certificate.status_code, 201, certificate.content)
        self.assertTrue(certificate.json()["certificate_code"].startswith("FAMILY-WS-"))

        self.client.force_authenticate(self.psy_member)
        self.client.post("/api/v1/institutes/psy/lms/courses/shared-course/enroll/")
        psy_session = self.psy_course.sessions.get().id
        self.client.post(
            f"/api/v1/institutes/psy/lms/courses/shared-course/sessions/{psy_session}/complete/"
        )
        psy_certificate = self.client.post(
            "/api/v1/institutes/psy/lms/courses/shared-course/certificate/issue/"
        )
        self.assertEqual(psy_certificate.status_code, 201, psy_certificate.content)
        self.assertTrue(psy_certificate.json()["certificate_code"].startswith("PSY-WS-"))

    def test_legacy_course_and_enrollment_payloads_match(self):
        self.client.force_authenticate(self.psy_member)
        self.client.post("/api/v1/psy/workshops/shared-course/enroll/")
        scoped_course = self.client.get("/api/v1/institutes/psy/lms/courses/shared-course/")
        legacy_course = self.client.get("/api/v1/psy/workshops/shared-course/")
        self.assertEqual(scoped_course.json(), legacy_course.json())
        self.assertEqual(scoped_course.json()["instructor_id"], self.therapist.therapist_profile.id)
        scoped_rows = self.client.get("/api/v1/institutes/psy/lms/enrollments/")
        legacy_rows = self.client.get("/api/v1/psy/patient/workshop-enrollments/")
        self.assertEqual(scoped_rows.json(), legacy_rows.json())
        self.assertIn("workshop_title", scoped_rows.json()[0])
        self.assertIn("patient_name", scoped_rows.json()[0])
