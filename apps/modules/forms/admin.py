from django import forms
from django.contrib import admin

from apps.modules.admin_scope import ModuleAdmin

from .models import Form, Response


class ResponseForm(forms.ModelForm):
    class Meta:
        model = Response
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        form = cleaned.get("form")
        version = cleaned.get("version")
        institute = cleaned.get("institute")
        if form is not None and institute is not None and form.institute_id != institute.pk:
            self.add_error("institute", "Institute must match the form.")
        if version is not None and form is not None and version.form_id != form.pk:
            self.add_error("version", "Version must belong to this form.")
        return cleaned


@admin.register(Form)
class FormAdmin(ModuleAdmin):
    legacy_model = "psychometricform"
    list_display = ("title", "institute", "slug", "version", "is_published")
    list_filter = ("is_published",)
    prepopulated_fields = {"slug": ("title",)}
    search_fields = ("title", "slug")


@admin.register(Response)
class ResponseAdmin(ModuleAdmin):
    legacy_model = "psychometricresponse"
    form = ResponseForm
    list_display = ("id", "institute", "form", "respondent", "status", "submitted_at")
    list_filter = ("status",)
