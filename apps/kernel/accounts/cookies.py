"""
تو این فایل دسترسی و رفرش توکن ها رو تنظیم میکنیم
"""

from django.conf import settings
from rest_framework.response import Response


def set_access_cookie(response: Response, access_token: str) -> None:
    response.set_cookie(
        settings.JWT_ACCESS_COOKIE,
        access_token,
        max_age=int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
        httponly=True,
        secure=settings.JWT_COOKIE_SECURE,
        samesite=settings.JWT_COOKIE_SAMESITE,
        path="/",
    )


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        settings.JWT_REFRESH_COOKIE,
        refresh_token,
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        httponly=True,
        secure=settings.JWT_COOKIE_SECURE,
        samesite=settings.JWT_COOKIE_SAMESITE,
        path=settings.JWT_REFRESH_COOKIE_PATH,
    )


def delete_jwt_cookies(response: Response) -> None:
    response.delete_cookie(settings.JWT_ACCESS_COOKIE, path="/")
    response.delete_cookie(
        settings.JWT_REFRESH_COOKIE, path=settings.JWT_REFRESH_COOKIE_PATH
    )
