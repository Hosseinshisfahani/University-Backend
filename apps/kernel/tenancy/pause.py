"""Short write pause for a module cutover.

Set TENANCY_WRITE_PAUSE to a list of module ids. Reads continue.
Paused mutations return 503. Gateway callbacks are not paused.
"""

from django.conf import settings
from django.http import JsonResponse

PAUSE_MARKERS = {
    "shop": ("/shop/",),
    "lms": ("/lms/", "/workshops"),
    "booking": ("/booking/", "/appointments/", "/session-types/"),
    "content": ("/content/", "/blog/", "/news/"),
    "forms": ("/forms/", "/responses/"),
    "reviews": ("/reviews/",),
}


def paused_modules() -> set[str]:
    return set(getattr(settings, "TENANCY_WRITE_PAUSE", []) or [])


class WritePauseMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
            return self.get_response(request)
        if "/finance/vandar/" in request.path:
            return self.get_response(request)
        paused = paused_modules()
        if not paused:
            return self.get_response(request)
        path = request.path
        for module_id, markers in PAUSE_MARKERS.items():
            if module_id in paused and any(marker in path for marker in markers):
                return JsonResponse(
                    {"detail": "این بخش موقتاً برای به‌روزرسانی بسته است."},
                    status=503,
                )
        return self.get_response(request)
