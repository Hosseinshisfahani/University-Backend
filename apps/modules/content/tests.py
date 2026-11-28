import importlib

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.institutes.psy_institute.legacy import allow_legacy_table_writes
from apps.institutes.psy_institute.models import BlogPost
from apps.modules.content.models import Post
from apps.kernel.tenancy.models import Institute
from apps.kernel.tenancy.services import grant_roles

User = get_user_model()


class ContentIsolationTests(TestCase):
    def setUp(self):
        self.psy = Institute.objects.get(slug="psy")
        self.family = Institute.objects.create(
            slug="family",
            name="خانواده",
            is_active=True,
            enabled_modules=["content"],
        )
        self.legal = Institute.objects.create(
            slug="legal",
            name="حقوقی",
            is_active=True,
            enabled_modules=[],
        )
        self.admin = User.objects.create_user(username="content_admin", password="x")
        grant_roles(user=self.admin, institute=self.family, roles=["admin"])
        Post.objects.create(
            institute=self.family,
            title="خانواده",
            slug="shared-slug",
            body="family",
            is_published=True,
        )
        Post.objects.create(
            institute=self.psy,
            title="روان",
            slug="shared-slug",
            body="psy",
            is_published=True,
        )
        self.client = APIClient()

    def test_same_slug_stays_inside_its_institute(self):
        family = self.client.get("/api/v1/institutes/family/content/posts/shared-slug/")
        psy = self.client.get("/api/v1/institutes/psy/content/posts/shared-slug/")
        self.assertEqual(family.status_code, 200)
        self.assertEqual(family.json()["body"], "family")
        self.assertEqual(psy.status_code, 200)
        self.assertEqual(psy.json()["body"], "psy")

    def test_admin_cannot_edit_another_institutes_post(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.patch(
            "/api/v1/institutes/psy/content/posts/shared-slug/",
            {"title": "دزدیده"},
            format="json",
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(
            Post.objects.get(institute=self.psy, slug="shared-slug").title,
            "روان",
        )

    def test_disabled_module_is_not_found_on_either_route(self):
        scoped = self.client.get("/api/v1/institutes/legal/content/posts/")
        self.assertEqual(scoped.status_code, 404)
        self.psy.enabled_modules = ["shop"]
        self.psy.save(update_fields=["enabled_modules"])
        legacy = self.client.get("/api/v1/psy/blog/")
        self.assertEqual(legacy.status_code, 404)

    def test_institute_without_an_adapter_gets_neutral_author_fields(self):
        family = self.client.get("/api/v1/institutes/family/content/posts/shared-slug/")
        psy = self.client.get("/api/v1/institutes/psy/content/posts/shared-slug/")
        self.assertEqual(family.status_code, 200)
        self.assertNotIn("author_therapist_id", family.json())
        self.assertIn("author_name", family.json())
        self.assertEqual(psy.status_code, 200)
        self.assertIn("author_therapist_id", psy.json())

    def test_legacy_blog_matches_the_scoped_post(self):
        scoped = self.client.get("/api/v1/institutes/psy/content/posts/shared-slug/")
        legacy = self.client.get("/api/v1/psy/blog/shared-slug/")
        self.assertEqual(scoped.status_code, 200)
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(scoped.json(), legacy.json())


class ContentCopyMigrationTests(TestCase):
    def test_copy_keeps_the_primary_key_and_the_existing_file_name(self):
        migration = importlib.import_module(
            "apps.modules.content.migrations.0002_copy_psy_content"
        )

        with allow_legacy_table_writes():
            old = BlogPost.objects.create(
                title="قدیم",
                slug="legacy-copy",
                body="متن",
                cover_image="psy/blog/kept.jpg",
            )
        migration._copy(apps, None)
        copied = Post.objects.get(pk=old.pk)
        self.assertEqual(copied.institute.slug, "psy")
        self.assertEqual(copied.slug, "legacy-copy")
        self.assertEqual(copied.cover_image.name, "psy/blog/kept.jpg")
        self.assertEqual(copied.created_at, old.created_at)
