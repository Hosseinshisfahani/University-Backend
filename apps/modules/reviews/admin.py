from django.contrib import admin

from apps.modules.admin_scope import ModuleAdmin

from .models import Review


@admin.register(Review)
class ReviewAdmin(ModuleAdmin):
    legacy_model = "therapistreview"
    list_display = ("id", "institute", "rating", "text_status", "author")
    list_filter = ("text_status",)
