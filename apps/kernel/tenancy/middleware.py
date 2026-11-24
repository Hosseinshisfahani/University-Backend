import json

from django.http import HttpResponse

from .hosts import describe_host
from .models import Institute
from .registry import BOOTSTRAP_INSTITUTE_SLUG, capability_for_legacy_path


class LegacyCapabilityMiddleware:
    """404 legacy psy routes whose capability is disabled for the psy institute.

    Clinical, ticket, finance and user routes are not capabilities and pass
    through. The institute is always psy: these URLs are the compatibility
    aliases, not a tenant selector.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/"):
            binding = describe_host(request.get_host())
            request.tenancy_host = binding
            if binding.kind in ("unknown", "inactive"):
                body = json.dumps({"detail": "یافت نشد."}).encode()
                return HttpResponse(body, status=404, content_type="application/json")
            if (
                request.path.startswith("/api/v1/psy/")
                and binding.kind == "institute"
                and binding.slug != BOOTSTRAP_INSTITUTE_SLUG
            ):
                body = json.dumps({"detail": "یافت نشد."}).encode()
                return HttpResponse(body, status=404, content_type="application/json")
        capability = capability_for_legacy_path(request.path)
        if capability is None:
            return self.get_response(request)
        institute = (
            Institute.objects.filter(slug=BOOTSTRAP_INSTITUTE_SLUG, is_active=True)
            .only("id", "enabled_modules", "is_active")
            .first()
        )
        enabled = institute.enabled_modules if institute is not None else []
        if capability not in enabled:
            body = json.dumps({"detail": "یافت نشد."}).encode()
            return HttpResponse(body, status=404, content_type="application/json")
        return self.get_response(request)
