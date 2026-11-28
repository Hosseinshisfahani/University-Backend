"""Django admin writes module tables, and frozen psychology tables stay read-only."""

from django.apps import apps
from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.urls import NoReverseMatch, reverse

from apps.institutes.psy_institute.legacy import (
    FROZEN_MODEL_NAMES,
    LegacyTable,
    LegacyTableFrozen,
    allow_legacy_table_writes,
)
from apps.institutes.psy_institute.models import (
    BlogPost,
    NewsSlide as LegacyNewsSlide,
    Product,
    SessionType as LegacySessionType,
    TherapistProfile,
    Workshop,
)
from apps.kernel.tenancy.models import Institute
from apps.kernel.tenancy.services import grant_roles
from apps.modules.booking.models import ServiceType
from apps.modules.content.models import NewsSlide, Post
from apps.modules.forms.models import Form
from apps.modules.lms.models import Course, Enrollment
from apps.modules.reviews.models import Review

User = get_user_model()


def _perm(app_label, codename):
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


class LegacyTableWriteTests(TestCase):
    def test_history_rows_can_be_read_and_direct_writes_are_refused(self):
        with allow_legacy_table_writes():
            post = BlogPost.objects.create(title="قدیم", slug="kept", body="متن")
        self.assertEqual(BlogPost.objects.get(pk=post.pk).title, "قدیم")

        with self.assertRaises(LegacyTableFrozen):
            BlogPost.objects.create(title="نو", slug="new", body="x")
        with self.assertRaises(LegacyTableFrozen):
            BlogPost.objects.filter(pk=post.pk).update(title="عوض")
        with self.assertRaises(LegacyTableFrozen):
            post.delete()
        post.refresh_from_db()
        self.assertEqual(post.title, "قدیم")
        self.assertEqual(BlogPost.objects.count(), 1)
        frozen = {
            model.__name__
            for model in apps.get_models()
            if issubclass(model, LegacyTable)
        }
        self.assertEqual(frozen, set(FROZEN_MODEL_NAMES))

        with self.assertRaises(LegacyTableFrozen):
            Workshop.objects.create(title="کارگاه", slug="ws", capacity=1, price=0)
        with self.assertRaises(LegacyTableFrozen):
            LegacyNewsSlide.objects.create(title="اسلاید")
        with self.assertRaises(LegacyTableFrozen):
            Product.objects.create(title="کتاب", slug="book", price=1)

    def test_clearing_a_user_still_nulls_a_historical_author(self):
        author = User.objects.create_user(username="old-author", password="x")
        with allow_legacy_table_writes():
            post = BlogPost.objects.create(title="قدیم", slug="author", body="متن", author=author)
        author.delete()
        post.refresh_from_db()
        self.assertIsNone(post.author_id)
        self.assertEqual(post.slug, "author")

    def test_clinic_profiles_stay_writable(self):
        user = User.objects.create_user(username="therapist", password="x")
        institute = Institute.objects.get(slug="psy")
        profile = TherapistProfile.objects.create(
            user=user,
            institute=institute,
            display_name="دکتر",
        )
        profile.display_name = "دکتر تازه"
        profile.save(update_fields=["display_name", "updated_at"])
        profile.refresh_from_db()
        self.assertEqual(profile.display_name, "دکتر تازه")


class ModuleAdminRegistryTests(TestCase):
    def test_frozen_models_are_absent_and_module_models_are_registered(self):
        call_command("check")
        for model in (
            Workshop,
            BlogPost,
            LegacyNewsSlide,
            LegacySessionType,
            Product,
        ):
            self.assertFalse(site.is_registered(model))
            with self.assertRaises(NoReverseMatch):
                reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")

        for model in (Course, Post, NewsSlide, ServiceType, Form, Review, Enrollment):
            self.assertTrue(site.is_registered(model))

        slide_admin = site._registry[NewsSlide]
        self.assertEqual(slide_admin.list_editable, ("sort_order", "is_published"))
        self.assertEqual(site._registry[Post].prepopulated_fields, {"slug": ("title",)})
        self.assertEqual(site._registry[Course].prepopulated_fields, {"slug": ("title",)})
        self.assertEqual(site._registry[ServiceType].prepopulated_fields, {"slug": ("name",)})
        self.assertIn("is_published", site._registry[NewsSlide].list_filter)

    def test_superuser_can_open_the_module_changelists(self):
        admin_user = User.objects.create_superuser(username="root", password="x", email="root@example.com")
        self.client.force_login(admin_user)
        for model in (Course, Post, NewsSlide, ServiceType, Form, Review):
            url = reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)


class ModuleAdminWriteTests(TestCase):
    def setUp(self):
        self.psy = Institute.objects.get(slug="psy")
        self.family = Institute.objects.create(
            slug="family",
            name="خانواده",
            is_active=True,
            enabled_modules=["lms", "content", "booking", "forms"],
        )
        self.root = User.objects.create_superuser(username="root2", password="x", email="root2@example.com")
        self.client.force_login(self.root)

    def test_course_post_and_slide_admin_write_the_module_tables(self):
        course = self.client.post(
            reverse("admin:lms_course_add"),
            {
                "institute": self.psy.pk,
                "title": "دوره ادمین",
                "slug": "admin-course",
                "description": "",
                "body_md": "",
                "instructor": "",
                "capacity": "12",
                "price": "0",
                "starts_at_0": "",
                "starts_at_1": "",
                "ends_at_0": "",
                "ends_at_1": "",
                "recording_url": "",
                "is_published": "on",
            },
        )
        self.assertEqual(course.status_code, 302, course.content[:500])
        saved = Course.objects.get(slug="admin-course")
        self.assertEqual(saved.institute_id, self.psy.pk)
        self.assertTrue(saved.is_published)
        self.assertEqual(Workshop.objects.count(), 0)

        post = self.client.post(
            reverse("admin:content_post_add"),
            {
                "institute": self.psy.pk,
                "title": "مقاله ادمین",
                "slug": "admin-post",
                "excerpt": "",
                "body": "متن",
                "author": "",
                "published_at_0": "",
                "published_at_1": "",
                "is_published": "on",
            },
        )
        self.assertEqual(post.status_code, 302, post.content[:500])
        self.assertEqual(Post.objects.get(slug="admin-post").body, "متن")
        self.assertEqual(BlogPost.objects.count(), 0)

        slide = self.client.post(
            reverse("admin:content_newsslide_add"),
            {
                "institute": self.psy.pk,
                "title": "اسلاید ادمین",
                "body": "",
                "link_url": "",
                "link_label": "",
                "sort_order": "3",
                "is_published": "on",
            },
        )
        self.assertEqual(slide.status_code, 302, slide.content[:500])
        self.assertEqual(NewsSlide.objects.get(title="اسلاید ادمین").sort_order, 3)
        self.assertEqual(LegacyNewsSlide.objects.count(), 0)

        service = self.client.post(
            reverse("admin:booking_servicetype_add"),
            {
                "institute": self.psy.pk,
                "name": "آنلاین",
                "slug": "admin-online",
                "modality": "online",
                "duration_minutes": "45",
                "price": "0",
                "buffer_minutes": "0",
                "sort_order": "0",
                "is_active": "on",
            },
        )
        self.assertEqual(service.status_code, 302, service.content[:500])
        self.assertTrue(ServiceType.objects.filter(institute=self.psy, slug="admin-online").exists())
        self.assertEqual(LegacySessionType.objects.count(), 0)

    def test_enrollment_form_rejects_a_course_from_another_institute(self):
        course = Course.objects.create(
            institute=self.family,
            title="خانواده",
            slug="family-course",
            capacity=4,
            price=0,
        )
        student = User.objects.create_user(username="student", password="x")
        request = RequestFactory().get("/")
        request.user = self.root
        form_class = site._registry[Enrollment].get_form(request)
        form = form_class(
            data={
                "institute": self.psy.pk,
                "workshop": course.pk,
                "user": student.pk,
                "status": "pending_payment",
                "price_snapshot": "0",
                "payment_ref": "",
                "deposit_ledger_ref": "",
                "refund_ledger_ref": "",
                "cancellation_reason": "",
                "hold_expires_at_0": "",
                "hold_expires_at_1": "",
                "canceled_at_0": "",
                "canceled_at_1": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("workshop", form.errors)
        self.assertEqual(Enrollment.objects.count(), 0)

    def test_legacy_workshop_permission_stays_inside_psychology(self):
        Course.objects.create(
            institute=self.psy,
            title="روان",
            slug="psy-course",
            capacity=4,
            price=0,
        )
        Course.objects.create(
            institute=self.family,
            title="خانواده",
            slug="family-course",
            capacity=4,
            price=0,
        )
        staff = User.objects.create_user(username="psy-staff", password="x", is_staff=True)
        staff.user_permissions.add(_perm("psy_institute", "change_workshop"))
        self.client.force_login(staff)
        response = self.client.get(reverse("admin:lms_course_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "روان")
        self.assertNotContains(response, "خانواده")

        family_course = Course.objects.get(slug="family-course")
        change = self.client.get(reverse("admin:lms_course_change", args=[family_course.pk]))
        self.assertRedirects(change, reverse("admin:index"))

        request = RequestFactory().get("/")
        request.user = User.objects.get(pk=staff.pk)
        course_admin = site._registry[Course]
        self.assertTrue(course_admin.has_change_permission(request))
        self.assertFalse(course_admin.has_add_permission(request))
        self.assertFalse(course_admin.has_change_permission(request, family_course))

    def test_institute_admin_does_not_see_another_institutes_courses(self):
        Course.objects.create(
            institute=self.psy,
            title="روان",
            slug="psy-only",
            capacity=4,
            price=0,
        )
        Course.objects.create(
            institute=self.family,
            title="خانواده",
            slug="family-only",
            capacity=4,
            price=0,
        )
        staff = User.objects.create_user(username="family-admin", password="x", is_staff=True)
        grant_roles(user=staff, institute=self.family, roles=["admin"])
        staff.user_permissions.add(_perm("lms", "change_course"))
        self.client.force_login(staff)
        response = self.client.get(reverse("admin:lms_course_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "خانواده")
        self.assertNotContains(response, "روان")
        denied = self.client.post(
            reverse("admin:lms_course_add"),
            {
                "institute": self.psy.pk,
                "title": "دزدیده",
                "slug": "stolen",
                "description": "",
                "body_md": "",
                "instructor": "",
                "capacity": "1",
                "price": "0",
                "starts_at_0": "",
                "starts_at_1": "",
                "ends_at_0": "",
                "ends_at_1": "",
                "recording_url": "",
            },
        )
        self.assertNotEqual(denied.status_code, 302)
        self.assertFalse(Course.objects.filter(slug="stolen").exists())
