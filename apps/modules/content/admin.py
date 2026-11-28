from django.contrib import admin

from apps.modules.admin_scope import ModuleAdmin

from .models import NewsSlide, Post, SitePage


@admin.register(Post)
class PostAdmin(ModuleAdmin):
    legacy_model = "blogpost"
    list_display = ("title", "institute", "slug", "is_published", "published_at")
    list_filter = ("is_published",)
    prepopulated_fields = {"slug": ("title",)}
    search_fields = ("title", "slug")


@admin.register(NewsSlide)
class NewsSlideAdmin(ModuleAdmin):
    legacy_model = "newsslide"
    list_display = ("title", "institute", "sort_order", "is_published", "updated_at")
    list_editable = ("sort_order", "is_published")
    list_filter = ("is_published",)
    search_fields = ("title",)


@admin.register(SitePage)
class SitePageAdmin(ModuleAdmin):
    legacy_model = "sitepage"
    list_display = ("key", "institute", "title")
    search_fields = ("key", "title")
