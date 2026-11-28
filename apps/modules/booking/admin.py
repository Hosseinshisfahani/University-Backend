from django.contrib import admin

from apps.modules.admin_scope import ModuleAdmin

from .models import (
    Appointment,
    AvailabilityException,
    LeaveRequest,
    ProviderAvailability,
    ProviderServiceOffer,
    ServiceType,
    Slot,
)


@admin.register(ServiceType)
class ServiceTypeAdmin(ModuleAdmin):
    legacy_model = "sessiontype"
    list_display = (
        "name",
        "institute",
        "slug",
        "modality",
        "duration_minutes",
        "price",
        "is_active",
    )
    list_filter = ("modality", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug")


@admin.register(ProviderServiceOffer)
class ProviderServiceOfferAdmin(ModuleAdmin):
    legacy_model = "therapistsessionoffer"
    institute_parents = ("provider", "service_type")
    list_display = ("id", "institute", "provider", "service_type", "is_active")
    list_filter = ("is_active",)


@admin.register(ProviderAvailability)
class ProviderAvailabilityAdmin(ModuleAdmin):
    legacy_model = "therapistavailability"
    institute_parents = ("provider",)
    list_display = ("provider", "institute", "weekday", "start_time", "end_time", "is_active")
    list_filter = ("is_active",)


@admin.register(AvailabilityException)
class AvailabilityExceptionAdmin(ModuleAdmin):
    legacy_model = "availabilityexception"
    institute_parents = ("provider",)
    list_display = ("id", "institute", "provider", "date", "is_day_off")


@admin.register(LeaveRequest)
class LeaveRequestAdmin(ModuleAdmin):
    legacy_model = "leaverequest"
    institute_parents = ("provider",)
    list_display = ("id", "institute", "provider", "starts_on", "ends_on", "status")
    list_filter = ("status",)


@admin.register(Slot)
class SlotAdmin(ModuleAdmin):
    legacy_model = "appointmentslot"
    institute_parents = ("provider", "service_type")
    list_display = ("provider", "institute", "service_type", "starts_at", "ends_at", "status")
    list_filter = ("status",)


@admin.register(Appointment)
class AppointmentAdmin(ModuleAdmin):
    legacy_model = "appointment"
    institute_parents = ("slot", "provider", "service_type")
    list_display = (
        "id",
        "institute",
        "customer",
        "provider",
        "starts_at",
        "status",
        "price_snapshot",
    )
    list_filter = ("status",)
