from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .hosts import describe_host, public_config, require_host_agreement
from .models import Institute
from .registry import REGISTRY


class InstituteCapabilitiesView(APIView):
    """Public module selection for an active institute. Not the full config."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, institute_slug):
        institute = get_object_or_404(Institute, slug=institute_slug, is_active=True)
        require_host_agreement(request, institute)
        enabled = [item for item in (institute.enabled_modules or []) if item in REGISTRY]
        return Response(
            {
                "slug": institute.slug,
                "name": institute.name,
                "frontend_mode": institute.frontend_mode,
                "enabled_modules": enabled,
            }
        )


class ResolveView(APIView):
    """Public no-store host resolution. The caller sends the original Host."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        binding = describe_host(request.get_host())
        if binding.kind in ("unknown", "inactive"):
            return Response({"detail": "یافت نشد."}, status=404)
        if binding.kind == "platform":
            payload = {"kind": "platform"}
        else:
            payload = {
                "kind": "institute",
                "slug": binding.slug,
                "name": binding.name,
                "frontend_mode": binding.frontend_mode,
                "canonical_origin": (
                    f"https://{binding.canonical_hostname}" if binding.canonical_hostname else ""
                ),
            }
        response = Response(payload)
        response["Cache-Control"] = "no-store"
        return response


class InstituteConfigView(APIView):
    """Public branding and capability projection. Not the full settings blob."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, institute_slug):
        institute = get_object_or_404(Institute, slug=institute_slug, is_active=True)
        binding = require_host_agreement(request, institute)
        response = Response(public_config(institute, binding))
        response["Cache-Control"] = "no-store"
        return response
