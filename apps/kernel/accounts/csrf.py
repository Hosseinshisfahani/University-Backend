"""CSRF for cookie auth mutations that cannot use cookie authentication.

Login, registration, refresh, logout and OTP must run when the access
token is missing or expired, so they set ``authentication_classes = []``.
DRF marks APIView csrf-exempt. These views opt back in explicitly.
Gateway callbacks stay exempt.
"""

from rest_framework.authentication import SessionAuthentication


def enforce_mutation_csrf(request) -> None:
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return
    SessionAuthentication().enforce_csrf(request)


class CsrfOnMutation:
    def initial(self, request, *args, **kwargs):
        enforce_mutation_csrf(request)
        super().initial(request, *args, **kwargs)
