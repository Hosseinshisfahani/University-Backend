from django.urls import path

from .views import InstituteCapabilitiesView, InstituteConfigView, ResolveView

app_name = "tenancy"

urlpatterns = [
    path("tenancy/resolve/", ResolveView.as_view(), name="resolve"),
    path(
        "institutes/<slug:institute_slug>/capabilities/",
        InstituteCapabilitiesView.as_view(),
        name="capabilities",
    ),
    path(
        "institutes/<slug:institute_slug>/config/",
        InstituteConfigView.as_view(),
        name="config",
    ),
]
