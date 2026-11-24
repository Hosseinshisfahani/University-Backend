from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.modules.forms.models import Form
from apps.modules.forms.services import publish_schema, score_answers, submit_response
from apps.kernel.tenancy.models import Institute
from apps.kernel.tenancy.services import grant_roles

User = get_user_model()


class FormVersionTests(TestCase):
    def test_used_versions_stay_frozen_and_scores_use_that_schema(self):
        institute = Institute.objects.get(slug="psy")
        author = User.objects.create_user(username="form_author", password="x")
        respondent = User.objects.create_user(username="form_taker", password="x")
        form = Form.objects.create(
            institute=institute,
            title="حال",
            slug="mood",
            schema={"scoring": {"mode": "sum", "fields": ["mood"]}},
            version=1,
            is_published=True,
            created_by=author,
        )
        publish_schema(form=form, schema=form.schema)
        first = submit_response(form=form, respondent=respondent, answers={"mood": "3"})
        self.assertEqual(first.score["total"], 3)

        publish_schema(
            form=form,
            schema={"scoring": {"mode": "sum", "fields": ["mood", "extra"]}},
        )
        form.refresh_from_db()
        self.assertEqual(form.version, 2)
        first.version.refresh_from_db()
        self.assertEqual(first.version.schema["scoring"]["fields"], ["mood"])
        self.assertEqual(score_answers(first.version.schema, {"mood": "3", "extra": "9"})["total"], 3)

    def test_the_same_slug_stays_inside_its_institute(self):
        psy = Institute.objects.get(slug="psy")
        family = Institute.objects.create(
            slug="family", name="خانواده", is_active=True, enabled_modules=["forms"]
        )
        user = User.objects.create_user(username="family_forms", password="x")
        grant_roles(user=user, institute=family, roles=["admin"])
        Form.objects.create(institute=psy, title="روان", slug="shared", schema={}, is_published=True)
        Form.objects.create(institute=family, title="خانواده", slug="shared", schema={}, is_published=True)
        client = APIClient()
        psy_row = client.get("/api/v1/institutes/psy/forms/shared/")
        family_row = client.get("/api/v1/institutes/family/forms/shared/")
        self.assertEqual(psy_row.json()["title"], "روان")
        self.assertEqual(family_row.json()["title"], "خانواده")
        client.force_authenticate(user)
        denied = client.patch(
            "/api/v1/institutes/psy/forms/shared/",
            {"title": "دزدیده"},
            format="json",
        )
        self.assertEqual(denied.status_code, 404)
