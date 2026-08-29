"""Development settings."""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = True

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# Secure cookies cannot be set over plain http://localhost.
JWT_COOKIE_SECURE = env.bool("JWT_COOKIE_SECURE", default=False)

# `next dev` hops to 3001+ when 3000 is taken. CSRF Origin must match the
# browser origin, so DEBUG always trusts these local frontend ports even if
# .env only lists :3000.
_DEV_FRONTEND_ORIGINS = [
    f"http://{host}:{port}"
    for host in ("localhost", "127.0.0.1")
    for port in range(3000, 3004)
]

CORS_ALLOWED_ORIGINS = list(
    dict.fromkeys(
        [
            *env.list("CORS_ALLOWED_ORIGINS", default=_DEV_FRONTEND_ORIGINS),
            *_DEV_FRONTEND_ORIGINS,
        ]
    )
)

CSRF_TRUSTED_ORIGINS = list(
    dict.fromkeys(
        [
            *env.list("CSRF_TRUSTED_ORIGINS", default=_DEV_FRONTEND_ORIGINS),
            *_DEV_FRONTEND_ORIGINS,
        ]
    )
)
