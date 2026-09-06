from django.contrib import admin

from . import models


@admin.register(models.TherapistProfile)
class TherapistProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "user", "is_active", "is_accepting_patients")
    search_fields = ("display_name", "user__username")


@admin.register(models.PatientProfile)
class PatientProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "phone", "national_id")
    search_fields = ("user__username", "national_id", "phone")


@admin.register(models.SessionType)
class SessionTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "modality", "duration_minutes", "price", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    list_filter = ("modality", "is_active")


@admin.register(models.TherapistAvailability)
class TherapistAvailabilityAdmin(admin.ModelAdmin):
    list_display = ("therapist", "weekday", "start_time", "end_time", "is_active")


@admin.register(models.AppointmentSlot)
class AppointmentSlotAdmin(admin.ModelAdmin):
    list_display = ("therapist", "session_type", "starts_at", "ends_at", "status")
    list_filter = ("status",)


@admin.register(models.Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "therapist", "starts_at", "status", "price_snapshot")
    list_filter = ("status",)


@admin.register(models.PsychometricForm)
class PsychometricFormAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "version", "is_published")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(models.Workshop)
class WorkshopAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "capacity", "price", "is_published")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(models.BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_published", "published_at")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(models.Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "type", "subject", "status", "created_at")
    list_filter = ("type", "status")


admin.site.register(models.TherapistSessionOffer)
admin.site.register(models.AvailabilityException)
admin.site.register(models.LeaveRequest)
admin.site.register(models.TherapistReview)
admin.site.register(models.SessionNote)
admin.site.register(models.PsychometricResponse)
admin.site.register(models.WorkshopEnrollment)
admin.site.register(models.WorkshopCertificate)
admin.site.register(models.WorkshopSession)
admin.site.register(models.WorkshopResource)
admin.site.register(models.WorkshopSessionProgress)
admin.site.register(models.SitePage)
admin.site.register(models.TicketMessage)
