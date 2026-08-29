from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("psy_institute", "0002_appointment_slot_gist_exclusion"),
    ]

    operations = [
        migrations.AddField(
            model_name="appointment",
            name="meeting_link",
            field=models.URLField(blank=True, max_length=500),
        ),
    ]
