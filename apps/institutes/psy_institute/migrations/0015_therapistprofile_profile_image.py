# Generated manually for therapist profile photo uploads.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("psy_institute", "0014_clinicalreport_fileaccessrequest"),
    ]

    operations = [
        migrations.AddField(
            model_name="therapistprofile",
            name="profile_image",
            field=models.ImageField(
                blank=True,
                max_length=500,
                upload_to="psy/therapists/",
                verbose_name="تصویر پروفایل",
            ),
        ),
    ]
