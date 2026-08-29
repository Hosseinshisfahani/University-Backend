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
