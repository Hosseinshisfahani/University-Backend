from django import forms
from django.contrib import admin

from apps.modules.admin_scope import ModuleAdmin

from .models import (
    Certificate,
    Course,
    CourseResource,
    CourseSession,
    Enrollment,
    SessionProgress,
)


class CourseResourceForm(forms.ModelForm):
    class Meta:
        model = CourseResource
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        workshop = cleaned.get("workshop")
        session = cleaned.get("session")
        institute = cleaned.get("institute")
        if workshop is not None and institute is not None and workshop.institute_id != institute.pk:
            self.add_error("institute", "Institute must match the course.")
        if session is not None and workshop is not None and session.workshop_id != workshop.pk:
            self.add_error("session", "Session must belong to this course.")
        if session is not None and institute is not None and session.institute_id != institute.pk:
            self.add_error("session", "Session must belong to this institute.")
        return cleaned


@admin.register(Course)
class CourseAdmin(ModuleAdmin):
    legacy_model = "workshop"
    list_display = ("title", "institute", "slug", "capacity", "price", "is_published")
    list_filter = ("is_published",)
    prepopulated_fields = {"slug": ("title",)}
    search_fields = ("title", "slug")


@admin.register(Enrollment)
class EnrollmentAdmin(ModuleAdmin):
    legacy_model = "workshopenrollment"
    institute_parents = ("workshop",)
    list_display = ("id", "institute", "workshop", "user", "status", "enrolled_at")
    list_filter = ("status",)


@admin.register(CourseSession)
class CourseSessionAdmin(ModuleAdmin):
    legacy_model = "workshopsession"
    institute_parents = ("workshop",)
    list_display = ("title", "institute", "workshop", "sort_order", "starts_at")


@admin.register(CourseResource)
class CourseResourceAdmin(ModuleAdmin):
    legacy_model = "workshopresource"
    form = CourseResourceForm
    list_display = ("title", "institute", "workshop", "kind", "sort_order")
    list_filter = ("kind",)


@admin.register(SessionProgress)
class SessionProgressAdmin(ModuleAdmin):
    legacy_model = "workshopsessionprogress"
    institute_path = "enrollment__institute"
    list_display = ("id", "enrollment", "session", "completed_at")


@admin.register(Certificate)
class CertificateAdmin(ModuleAdmin):
    legacy_model = "workshopcertificate"
    institute_path = "enrollment__institute"
    list_display = ("certificate_code", "enrollment", "issued_at")
    search_fields = ("certificate_code",)
