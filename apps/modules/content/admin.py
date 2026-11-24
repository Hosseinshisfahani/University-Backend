from django.contrib import admin

from .models import NewsSlide, Post, SitePage


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("title", "institute", "slug", "is_published")
    exclude = ("institute",)


@admin.register(NewsSlide)
class NewsSlideAdmin(admin.ModelAdmin):
    list_display = ("title", "institute", "sort_order", "is_published")


@admin.register(SitePage)
class SitePageAdmin(admin.ModelAdmin):
    list_display = ("key", "institute", "title")
