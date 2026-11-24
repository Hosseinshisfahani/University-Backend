"""Shared HTTP middleware for the modular monolith."""


class ForceApiTrailingSlashMiddleware:
    """
    Next.js rewrites often strip trailing slashes before proxying to Django.

    Django's CommonMiddleware cannot 301-redirect POST/PUT/PATCH/DELETE while
    preserving the body, so a missing slash becomes a 500. Normalize /api/*
    paths before URL resolution so APPEND_SLASH is never needed for the API.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        if path.startswith("/api/") and not path.endswith("/"):
            request.path_info = f"{path}/"
            # Keep META in sync for anything that reads SCRIPT/PATH directly.
            request.META["PATH_INFO"] = request.path_info
        return self.get_response(request)


class DisableApiResponseCachingMiddleware:
    """Stop browsers and the edge CDN from storing API responses.

    ayehh.ir sits behind WCDN with a SMART policy. GET 200s that omit
    Cache-Control are cached, including an empty session-type list and an
    empty admin offers list. Later saves then look like they never persisted.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        path = request.path_info or request.path
        if path.startswith("/api/"):
            response["Cache-Control"] = "private, no-store, max-age=0"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
            response["CDN-Cache-Control"] = "no-store"
        return response
