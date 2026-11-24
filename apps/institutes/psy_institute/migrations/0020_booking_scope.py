import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("booking", "0001_booking_scope"),
        ("psy_institute", "0019_review_bridge"),
    ]

    operations = [
        migrations.AddField(
            model_name="therapistprofile",
            name="provider",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="therapist_profile",
                to="booking.provider",
                verbose_name="ارائه‌دهنده نوبت",
            ),
        ),
    ]
