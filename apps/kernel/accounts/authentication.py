"""
آقا ما این بخش رو طوری طراحی کردیم که به جای اینکه  برای دریافت توکن از سرور بپرسیم، از کوکی استفاده کنیم.
خارجکی اش میشه:
Cookie-based JWT authentication.

"""

from django.conf import settings
from rest_framework import exceptions
from rest_framework.authentication import CSRFCheck
from rest_framework_simplejwt.authentication import JWTAuthentication


class CookieJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        raw_token = request.COOKIES.get(settings.JWT_ACCESS_COOKIE)
        if raw_token is None:
            return None

        validated_token = self.get_validated_token(raw_token)
        self.enforce_csrf(request)
        return self.get_user(validated_token), validated_token

    def enforce_csrf(self, request) -> None:
        """Same behavior as DRF's SessionAuthentication.enforce_csrf."""
        check = CSRFCheck(lambda req: None)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            raise exceptions.PermissionDenied(f"CSRF failed: {reason}")
