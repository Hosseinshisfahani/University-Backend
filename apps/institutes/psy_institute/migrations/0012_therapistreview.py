# Generated manually for patient-to-therapist reviews.

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("psy_institute", "0011_blog_cover_image_upload"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TherapistReview",
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
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ایجاد")),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, verbose_name="تاریخ به‌روزرسانی"),
                ),
                (
                    "rating",
                    models.PositiveSmallIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(5),
                        ],
                        verbose_name="امتیاز",
                    ),
                ),
                ("body", models.TextField(blank=True, verbose_name="متن نظر")),
                (
                    "text_status",
                    models.CharField(
                        choices=[
                            ("none", "No text"),
                            ("pending", "Pending"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                        ],
                        db_index=True,
                        default="none",
                        max_length=16,
                        verbose_name="وضعیت متن",
                    ),
                ),
                (
                    "reviewed_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="تاریخ بررسی"
                    ),
                ),
                ("admin_note", models.TextField(blank=True, verbose_name="یادداشت مدیر")),
                (
                    "appointment",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="review",
                        to="psy_institute.appointment",
                        verbose_name="نوبت",
                    ),
                ),
                (
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="therapist_reviews",
                        to="psy_institute.patientprofile",
                        verbose_name="مراجع",
                    ),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="psy_review_moderations",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="بررسی‌کننده",
                    ),
                ),
                (
                    "therapist",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="reviews",
                        to="psy_institute.therapistprofile",
                        verbose_name="درمانگر",
                    ),
                ),
            ],
            options={
                "verbose_name": "نظر مراجع",
                "verbose_name_plural": "نظرات مراجعان",
                "ordering": ["-created_at"],
            },
        ),
    ]
