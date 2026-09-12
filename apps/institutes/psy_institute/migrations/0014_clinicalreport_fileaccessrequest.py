# Generated manually for private clinical reports and file-access requests.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("psy_institute", "0013_newsslide"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClinicalReport",
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
                ("summary", models.TextField(verbose_name="خلاصه جلسه")),
                ("assessment", models.TextField(verbose_name="ارزیابی بالینی")),
                ("treatment_plan", models.TextField(verbose_name="طرح درمان")),
                (
                    "risk_flags",
                    models.JSONField(
                        blank=True, default=list, verbose_name="پرچم‌های خطر"
                    ),
                ),
                (
                    "appointment",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="clinical_report",
                        to="psy_institute.appointment",
                        verbose_name="نوبت",
                    ),
                ),
                (
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="clinical_reports",
                        to="psy_institute.patientprofile",
                        verbose_name="مراجع",
                    ),
                ),
                (
                    "therapist",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="clinical_reports",
                        to="psy_institute.therapistprofile",
                        verbose_name="درمانگر",
                    ),
                ),
            ],
            options={
                "verbose_name": "گزارش بالینی",
                "verbose_name_plural": "گزارش‌های بالینی",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="FileAccessRequest",
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
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                            ("expired", "Expired"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                        verbose_name="وضعیت",
                    ),
                ),
                ("reason", models.TextField(blank=True, verbose_name="دلیل")),
                (
                    "decision_note",
                    models.TextField(blank=True, verbose_name="یادداشت تصمیم"),
                ),
                (
                    "decided_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="تاریخ تصمیم"
                    ),
                ),
                (
                    "expires_at",
                    models.DateTimeField(blank=True, null=True, verbose_name="انقضا"),
                ),
                (
                    "granted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="granted_file_access_requests",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="تأییدکننده",
                    ),
                ),
                (
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="file_access_requests",
                        to="psy_institute.patientprofile",
                        verbose_name="مراجع",
                    ),
                ),
                (
                    "therapist",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="file_access_requests",
                        to="psy_institute.therapistprofile",
                        verbose_name="درمانگر",
                    ),
                ),
            ],
            options={
                "verbose_name": "درخواست دسترسی پرونده",
                "verbose_name_plural": "درخواست‌های دسترسی پرونده",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="clinicalreport",
            index=models.Index(
                fields=["patient", "-created_at"],
                name="psy_institu_patient_c8e91a_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="clinicalreport",
            index=models.Index(
                fields=["therapist", "-created_at"],
                name="psy_institu_therapi_a4f21c_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="fileaccessrequest",
            index=models.Index(
                fields=["patient", "status"],
                name="psy_institu_patient_f1b8d2_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="fileaccessrequest",
            index=models.Index(
                fields=["therapist", "status"],
                name="psy_institu_therapi_c9d03e_idx",
            ),
        ),
    ]
