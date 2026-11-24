import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Institute",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ایجاد")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="تاریخ به‌روزرسانی")),
                ("slug", models.SlugField(max_length=64, unique=True, verbose_name="شناسه")),
                ("name", models.CharField(max_length=200, verbose_name="نام")),
                ("is_active", models.BooleanField(default=False, verbose_name="فعال")),
                ("enabled_modules", models.JSONField(default=list, verbose_name="ماژول‌های فعال")),
                (
                    "frontend_mode",
                    models.CharField(
                        choices=[("standard", "استاندارد"), ("custom", "سفارشی")],
                        default="standard",
                        max_length=16,
                        verbose_name="حالت فرانت",
                    ),
                ),
                ("settings", models.JSONField(blank=True, default=dict, verbose_name="تنظیمات")),
            ],
            options={
                "verbose_name": "مرکز",
                "verbose_name_plural": "مراکز",
                "ordering": ["slug"],
            },
        ),
        migrations.CreateModel(
            name="InstituteMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ایجاد")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="تاریخ به‌روزرسانی")),
                ("is_active", models.BooleanField(default=True, verbose_name="فعال")),
                (
                    "institute",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memberships",
                        to="tenancy.institute",
                        verbose_name="مرکز",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="institute_memberships",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="کاربر",
                    ),
                ),
            ],
            options={
                "verbose_name": "عضویت مرکز",
                "verbose_name_plural": "عضویت‌های مرکز",
            },
        ),
        migrations.CreateModel(
            name="InstituteMembershipRole",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ایجاد")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="تاریخ به‌روزرسانی")),
                (
                    "role",
                    models.CharField(
                        choices=[("admin", "مدیر"), ("staff", "کارشناس"), ("member", "عضو")],
                        max_length=16,
                        verbose_name="نقش",
                    ),
                ),
                (
                    "membership",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="role_rows",
                        to="tenancy.institutemembership",
                        verbose_name="عضویت",
                    ),
                ),
            ],
            options={
                "verbose_name": "نقش عضویت",
                "verbose_name_plural": "نقش‌های عضویت",
            },
        ),
        migrations.AddConstraint(
            model_name="institutemembership",
            constraint=models.UniqueConstraint(
                fields=("user", "institute"),
                name="uniq_membership_user_institute",
            ),
        ),
        migrations.AddConstraint(
            model_name="institutemembershiprole",
            constraint=models.UniqueConstraint(
                fields=("membership", "role"),
                name="uniq_membership_role",
            ),
        ),
    ]
