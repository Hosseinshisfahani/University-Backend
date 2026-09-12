# Generated manually for landing news slides.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("psy_institute", "0012_therapistreview"),
    ]

    operations = [
        migrations.CreateModel(
            name="NewsSlide",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ایجاد"),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, verbose_name="تاریخ به‌روزرسانی"),
                ),
                ("title", models.CharField(max_length=200, verbose_name="عنوان")),
                ("body", models.TextField(blank=True, verbose_name="متن")),
                (
                    "image",
                    models.ImageField(
                        blank=True,
                        max_length=500,
                        upload_to="psy/news/",
                        verbose_name="تصویر",
                    ),
                ),
                (
                    "link_url",
                    models.CharField(
                        blank=True,
                        help_text="Internal path or absolute URL.",
                        max_length=500,
                        verbose_name="لینک",
                    ),
                ),
                (
                    "link_label",
                    models.CharField(blank=True, max_length=80, verbose_name="متن دکمه"),
                ),
                (
                    "sort_order",
                    models.PositiveIntegerField(default=0, verbose_name="ترتیب"),
                ),
                (
                    "is_published",
                    models.BooleanField(default=False, verbose_name="منتشر شده"),
                ),
            ],
            options={
                "verbose_name": "اسلاید اخبار",
                "verbose_name_plural": "اسلایدهای اخبار",
                "ordering": ["sort_order", "-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="newsslide",
            index=models.Index(
                fields=["is_published", "sort_order"],
                name="psy_institu_is_publ_e7b2a4_idx",
            ),
        ),
    ]
