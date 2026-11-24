from django.contrib import admin

from .models import Institute, InstituteDomain, InstituteMembership, InstituteMembershipRole


class RoleInline(admin.TabularInline):
    model = InstituteMembershipRole
    extra = 0


class MembershipInline(admin.TabularInline):
    model = InstituteMembership
    extra = 0
    show_change_link = True


@admin.register(Institute)
class InstituteAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "is_active", "frontend_mode")
    inlines = [MembershipInline]


@admin.register(InstituteDomain)
class InstituteDomainAdmin(admin.ModelAdmin):
    list_display = ("hostname", "institute", "is_active", "is_canonical", "verified_at")
    search_fields = ("hostname",)


@admin.register(InstituteMembership)
class InstituteMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "institute", "is_active")
    list_filter = ("institute", "is_active")
    inlines = [RoleInline]
