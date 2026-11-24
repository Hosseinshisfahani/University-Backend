"""
Root URL configuration.

All client-facing APIs are versioned under /api/v1/. Each domain app owns
its own urls.py and is included here as it is implemented.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import Http404
from django.urls import include, path, re_path
from django.views.static import serve

def guarded_media(request, path, document_root=None, **kwargs):
    """Paid files and certificates are downloaded through authenticated actions."""
    normalized = path.lstrip("/")
    if normalized.startswith("psy/shop/files/") or normalized.startswith("psy/certificates/"):
        raise Http404()
    parts = normalized.split("/", 2)
    if len(parts) >= 3 and parts[0] in {"shop", "lms"} and parts[2].startswith("files/"):
        raise Http404()
    if normalized.startswith("lms/") and "/certificates/" in normalized:
        raise Http404()
    return serve(request, path, document_root=document_root, **kwargs)
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


api_v1_patterns = [
    path("", include("apps.kernel.core.urls")),
    path("auth/", include("apps.kernel.accounts.urls")),
    path("", include("apps.kernel.tenancy.urls")),
    path("finance/", include("apps.kernel.finance.urls")),
    path("notifications/", include("apps.kernel.notifications.urls")),
    path("psy/", include("apps.institutes.psy_institute.urls")),
    path(
        "institutes/<slug:institute_slug>/content/",
        include("apps.modules.content.urls"),
    ),
    path(
        "institutes/<slug:institute_slug>/",
        include("apps.modules.forms.urls"),
    ),
    path(
        "institutes/<slug:institute_slug>/shop/",
        include("apps.modules.shop.urls"),
    ),
    path(
        "institutes/<slug:institute_slug>/lms/",
        include("apps.modules.lms.urls"),
    ),
    path(
        "institutes/<slug:institute_slug>/booking/",
        include("apps.modules.booking.urls"),
    ),
    path(
        "institutes/<slug:institute_slug>/reviews/",
        include("apps.modules.reviews.urls"),
    ),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("api/v1/", include(api_v1_patterns)),
]

if settings.DEBUG:
    urlpatterns += [
        re_path(
            r"^media/(?P<path>.*)$",
            guarded_media,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
else:
    urlpatterns += [
        re_path(
            r"^media/(?P<path>.*)$",
            guarded_media,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
