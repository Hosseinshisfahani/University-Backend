from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.institutes.psy_institute.models import BlogPost
from apps.kernel.tenancy.models import Institute
from apps.kernel.tenancy.registry import validate_enabled_modules
from apps.kernel.tenancy.services import TenancyError, grant_psy_role, grant_roles, is_institute_admin

User = get_user_model()


class MembershipTests(TestCase):
    def test_psy_role_writes_legacy_group_and_keeps_other_roles(self):
        user = User.objects.create_user(username="both", password="x")
        grant_psy_role(user, "staff", provision_profile=False)
        grant_psy_role(user, "member", provision_profile=False)
        names = set(user.groups.values_list("name", flat=True))
        self.assertIn("psy_therapist", names)
        self.assertIn("psy_patient", names)
        self.assertTrue(is_institute_admin(user, "psy") is False)

    def test_staff_flag_is_not_an_institute_admin(self):
        user = User.objects.create_user(username="staffonly", password="x", is_staff=True)
        self.assertFalse(is_institute_admin(user, "psy"))

    def test_admin_role_is_institute_admin(self):
        user = User.objects.create_user(username="clinicadmin", password="x")
        grant_psy_role(user, "admin", provision_profile=False)
        self.assertTrue(is_institute_admin(user, "psy"))
        self.assertTrue(user.groups.filter(name="psy_admin").exists())

    def test_new_institute_cannot_enable_unready_modules(self):
        other = Institute.objects.create(slug="legal", name="حقوق", is_active=True)
        with self.assertRaises(ValueError):
            validate_enabled_modules(other.slug, ["not-a-module"])
        with self.assertRaises(TenancyError):
            grant_roles(user=User.objects.create_user("nobody", password="x"), institute=other, roles=["nope"])

    def test_disabling_content_hides_legacy_blog(self):
        institute = Institute.objects.get(slug="psy")
        institute.enabled_modules = ["reviews", "forms", "shop", "lms", "booking"]
        institute.save(update_fields=["enabled_modules"])
        BlogPost.objects.create(title="t", slug="t", body="b")
        response = self.client.get("/api/v1/psy/blog/")
        self.assertEqual(response.status_code, 404)

    def test_capabilities_are_public(self):
        response = self.client.get(reverse("tenancy:capabilities", args=["psy"]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("content", response.json()["enabled_modules"])
        self.assertEqual(response.json()["frontend_mode"], "custom")

    def test_two_institutes_do_not_share_admin(self):
        other = Institute.objects.create(
            slug="family",
            name="خانواده",
            is_active=True,
            enabled_modules=[],
        )
        user = User.objects.create_user(username="psyadmin", password="x")
        grant_psy_role(user, "admin", provision_profile=False)
        client = APIClient()
        client.force_authenticate(user)
        self.assertTrue(is_institute_admin(user, "psy"))
        self.assertFalse(is_institute_admin(user, other.slug))
        self.assertFalse(Group.objects.filter(name="family_admin").exists())


class DomainAndPauseTests(TestCase):
    def test_verification_and_canonical_switch(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.kernel.tenancy.domains import (
            DomainError,
            activate_canonical,
            begin_verification,
            confirm_verification,
            mark_tls_ready,
            normalize_hostname,
        )
        from apps.kernel.tenancy.models import InstituteDomain

        with self.assertRaises(DomainError):
            normalize_hostname("https://evil.example/path")
        self.assertEqual(normalize_hostname("WWW.Example.com."), "www.example.com")
        institute = Institute.objects.create(slug="family", name="خانواده", is_active=True)
        domain, token = begin_verification(institute=institute, hostname="family.example")
        with self.assertRaises(DomainError):
            confirm_verification(hostname="family.example", token="nope")
        confirm_verification(hostname="family.example", token=token)
        with self.assertRaises(DomainError):
            activate_canonical(hostname="family.example")
        mark_tls_ready(hostname="family.example")
        activate_canonical(hostname="family.example")
        self.assertTrue(InstituteDomain.objects.get(hostname="family.example").is_canonical)
        other, other_token = begin_verification(institute=institute, hostname="www.family.example")
        self.assertNotEqual(other.hostname, domain.hostname)
        confirm_verification(hostname="www.family.example", token=other_token)
        mark_tls_ready(hostname="www.family.example")
        activate_canonical(hostname="www.family.example")
        domain.refresh_from_db()
        self.assertFalse(domain.is_canonical)
        expired, expired_token = begin_verification(institute=institute, hostname="old.family.example")
        expired.verification_expires_at = timezone.now() - timedelta(minutes=1)
        expired.save(update_fields=["verification_expires_at"])
        with self.assertRaises(DomainError):
            confirm_verification(hostname="old.family.example", token=expired_token)

    def test_unknown_host_fails_closed_and_pause_blocks_writes(self):
        from django.test import override_settings

        with override_settings(DEBUG=False, ALLOWED_HOSTS=["evil.example", "testserver"]):
            missing = self.client.get("/api/v1/tenancy/resolve/", HTTP_HOST="evil.example")
            self.assertEqual(missing.status_code, 404)
        paused = override_settings(TENANCY_WRITE_PAUSE=["content"])
        paused.enable()
        self.addCleanup(paused.disable)
        response = self.client.post("/api/v1/institutes/psy/content/posts/", {})
        self.assertEqual(response.status_code, 503)

    def test_onboard_command_creates_an_inactive_institute(self):
        from django.core.management import call_command

        call_command(
            "onboard_institute",
            slug="legal",
            name="حقوق",
            modules="content",
        )
        institute = Institute.objects.get(slug="legal")
        self.assertFalse(institute.is_active)
        self.assertEqual(institute.frontend_mode, "standard")
        self.assertEqual(institute.enabled_modules, ["content"])


class IsolationConstraintTests(TestCase):
    def test_an_inactive_domain_cannot_be_canonical(self):
        from django.db import IntegrityError

        from apps.kernel.tenancy.models import InstituteDomain

        institute = Institute.objects.create(slug="clinic", name="کلینیک", is_active=True)
        domain = InstituteDomain.objects.create(
            institute=institute,
            hostname="clinic.example",
            is_active=False,
            is_canonical=False,
        )
        domain.is_canonical = True
        with self.assertRaises(IntegrityError):
            domain.save()

    def test_shop_shipping_fee_uses_institute_settings(self):
        from decimal import Decimal

        from apps.modules.shop.services import _shipping_fee

        institute = Institute.objects.create(
            slug="market",
            name="فروش",
            is_active=True,
            settings={"modules": {"shop": {"shipping_fee": 25000}}},
        )
        self.assertEqual(_shipping_fee(institute), Decimal("25000"))
