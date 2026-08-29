from django.conf import settings
from django.test import TestCase
from django.urls import reverse
import json

from .models import User


class CookieJWTAuthFlowTests(TestCase):
    """End-to-end flow: login -> me -> refresh -> logout."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="student", password="s3cret-pass")

    def login(self):
        return self.client.post(
            reverse("accounts:login"),
            {"username": "student", "password": "s3cret-pass"},
        )

    def test_login_sets_httponly_cookies_and_hides_tokens(self):
        response = self.login()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["username"], "student")
        # Tokens must never appear in the body.
        self.assertNotIn("access", response.json())
        self.assertNotIn("refresh", response.json())

        access = response.cookies[settings.JWT_ACCESS_COOKIE]
        refresh = response.cookies[settings.JWT_REFRESH_COOKIE]
        for cookie in (access, refresh):
            self.assertTrue(cookie["httponly"])
            self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(refresh["path"], settings.JWT_REFRESH_COOKIE_PATH)

    def test_login_with_bad_credentials_fails(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "student", "password": "wrong"},
        )
        self.assertEqual(response.status_code, 401)

    def test_me_requires_auth_cookie(self):
        response = self.client.get(reverse("accounts:me"))
        self.assertEqual(response.status_code, 401)

        self.login()
        response = self.client.get(reverse("accounts:me"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "student")

    def test_refresh_rotates_tokens(self):
        self.login()
        old_refresh = self.client.cookies[settings.JWT_REFRESH_COOKIE].value

        response = self.client.post(reverse("accounts:refresh"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("access", response.json())

        new_refresh = response.cookies[settings.JWT_REFRESH_COOKIE].value
        self.assertNotEqual(old_refresh, new_refresh)

    def test_refresh_without_cookie_fails(self):
        response = self.client.post(reverse("accounts:refresh"))
        self.assertEqual(response.status_code, 401)

    def test_logout_clears_cookies_and_blacklists_refresh(self):
        self.login()
        old_refresh = self.client.cookies[settings.JWT_REFRESH_COOKIE].value

        response = self.client.post(reverse("accounts:logout"))
        self.assertEqual(response.status_code, 200)
        # Cookies are expired by the response.
        self.assertEqual(response.cookies[settings.JWT_ACCESS_COOKIE].value, "")
        self.assertEqual(response.cookies[settings.JWT_REFRESH_COOKIE].value, "")

        # The blacklisted refresh token must be rejected.
        self.client.cookies[settings.JWT_REFRESH_COOKIE] = old_refresh
        response = self.client.post(reverse("accounts:refresh"))
        self.assertEqual(response.status_code, 401)


class RegisterFlowTests(TestCase):
    def test_register_creates_patient_and_sets_cookies(self):
        response = self.client.post(
            reverse("accounts:register"),
            data=json.dumps(
                {
                    "username": "newpatient",
                    "password": "Pass1234!",
                    "password_confirm": "Pass1234!",
                    "email": "new@example.com",
                    "phone": "09121112233",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["user"]["username"], "newpatient")
        self.assertIn("psy_patient", body["user"]["groups"])
        self.assertNotIn("access", body)
        self.assertIn(settings.JWT_ACCESS_COOKIE, response.cookies)

        user = User.objects.get(username="newpatient")
        self.assertTrue(hasattr(user, "patient_profile"))
        self.assertEqual(user.patient_profile.phone, "09121112233")

    def test_register_duplicate_username_fails(self):
        User.objects.create_user(username="taken", password="Pass1234!")
        response = self.client.post(
            reverse("accounts:register"),
            data=json.dumps(
                {
                    "username": "taken",
                    "password": "Pass1234!",
                    "password_confirm": "Pass1234!",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_register_password_mismatch_fails(self):
        response = self.client.post(
            reverse("accounts:register"),
            data=json.dumps(
                {
                    "username": "mismatch",
                    "password": "Pass1234!",
                    "password_confirm": "Other1234!",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
