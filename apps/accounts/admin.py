from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("تلفن", {"fields": ("phone",)}),)
    list_display = (*UserAdmin.list_display, "phone")
    search_fields = (*UserAdmin.search_fields, "phone")