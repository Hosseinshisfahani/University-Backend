from django.conf import settings
from django.db import models

from apps.kernel.tenancy.models import InstituteScopedModel


def blog_upload(instance, filename: str) -> str:
    return f"content/{instance.institute.slug}/blog/{filename}"


def news_upload(instance, filename: str) -> str:
    return f"content/{instance.institute.slug}/news/{filename}"


class Post(InstituteScopedModel):
    title = models.CharField(max_length=200, verbose_name="عنوان")
    slug = models.SlugField(max_length=50, verbose_name="شناسه")
    excerpt = models.TextField(blank=True, verbose_name="چکیده")
    body = models.TextField(verbose_name="متن")
    cover_image = models.ImageField(
        upload_to=blog_upload,
        blank=True,
        max_length=500,
        verbose_name="تصویر جلد",
    )
    is_published = models.BooleanField(default=False, verbose_name="منتشر شده")
    published_at = models.DateTimeField(null=True, blank=True, verbose_name="تاریخ انتشار")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="content_posts",
        verbose_name="نویسنده",
    )

    class Meta:
        ordering = ["-published_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["institute", "slug"], name="uniq_content_post_slug"),
        ]
        verbose_name = "مقاله"
        verbose_name_plural = "مقالات"


class NewsSlide(InstituteScopedModel):
    title = models.CharField(max_length=200, verbose_name="عنوان")
    body = models.TextField(blank=True, verbose_name="متن")
    image = models.ImageField(
        upload_to=news_upload,
        blank=True,
        max_length=500,
        verbose_name="تصویر",
    )
    link_url = models.CharField(max_length=500, blank=True, verbose_name="لینک")
    link_label = models.CharField(max_length=80, blank=True, verbose_name="متن دکمه")
    sort_order = models.PositiveIntegerField(default=0, verbose_name="ترتیب")
    is_published = models.BooleanField(default=False, verbose_name="منتشر شده")

    class Meta:
        ordering = ["sort_order", "-created_at"]
        verbose_name = "اسلاید اخبار"
        verbose_name_plural = "اسلایدهای اخبار"


class SitePage(InstituteScopedModel):
    key = models.CharField(max_length=64, verbose_name="کلید")
    title = models.CharField(max_length=200, verbose_name="عنوان")
    body = models.JSONField(default=dict, blank=True, verbose_name="متن")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["institute", "key"], name="uniq_content_page_key"),
        ]
        verbose_name = "صفحه سایت"
        verbose_name_plural = "صفحات سایت"
