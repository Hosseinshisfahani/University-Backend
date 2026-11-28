from django.contrib import admin
from django.utils.html import format_html

from . import models
from .forms import TherapistProfileAdminForm


@admin.register(models.TherapistProfile)
class TherapistProfileAdmin(admin.ModelAdmin):
    form = TherapistProfileAdminForm
    list_display = ("display_name", "user", "is_active", "is_accepting_patients")
    search_fields = ("display_name", "user__username")
    readonly_fields = ("profile_image_preview",)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "user",
                    "display_name",
                    "profile_image",
                    "profile_image_preview",
                    "bio",
                    "specialties",
                    "is_accepting_patients",
                    "is_active",
                )
            },
        ),
    )

    @admin.display(description="پیش‌نمایش تصویر")
    def profile_image_preview(self, obj):
        if not obj or not obj.profile_image:
            return "—"
        return format_html(
            '<img src="{}" alt="" style="height:96px;width:96px;object-fit:cover;border-radius:999px;" />',
            obj.profile_image.url,
        )


@admin.register(models.PatientProfile)
class PatientProfileAdmin(admin.ModelAdmin):
    exclude = ("institute",)
    list_display = ("id", "user", "phone", "national_id")
    search_fields = ("user__username", "national_id", "phone")


@admin.register(models.Ticket)
class TicketAdmin(admin.ModelAdmin):
    exclude = ("institute",)
    list_display = ("id", "patient", "type", "subject", "status", "created_at")
    list_filter = ("type", "status")


admin.site.register(models.SessionNote)


@admin.register(models.ClinicalReport)
class ClinicalReportAdmin(admin.ModelAdmin):
    exclude = ("institute",)
    list_display = ("id", "appointment", "therapist", "patient", "created_at")
    list_filter = ("therapist",)
    search_fields = (
        "patient__user__username",
        "therapist__display_name",
        "summary",
    )
    readonly_fields = ("therapist", "patient", "appointment", "created_at", "updated_at")


@admin.register(models.FileAccessRequest)
class FileAccessRequestAdmin(admin.ModelAdmin):
    exclude = ("institute",)
    list_display = (
        "id",
        "therapist",
        "patient",
        "status",
        "granted_by",
        "expires_at",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("therapist__display_name", "patient__user__username")
    readonly_fields = (
        "therapist",
        "patient",
        "granted_by",
        "decided_at",
        "expires_at",
        "created_at",
        "updated_at",
    )


admin.site.register(models.TicketMessage)
