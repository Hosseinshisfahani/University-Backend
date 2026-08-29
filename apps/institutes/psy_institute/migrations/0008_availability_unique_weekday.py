from datetime import date, datetime

from django.db import migrations, models


def dedupe_availability(apps, schema_editor):
    TherapistAvailability = apps.get_model("psy_institute", "TherapistAvailability")
    seen: dict[tuple[int, int], object] = {}
    extras = []
    for row in TherapistAvailability.objects.order_by("id"):
        key = (row.therapist_id, row.weekday)
        kept = seen.get(key)
        if kept is None:
            seen[key] = row
            continue
        keep, drop = _prefer_longer_window(kept, row)
        seen[key] = keep
        extras.append(drop)
    for row in extras:
        row.delete()


def _prefer_longer_window(a, b):
    if _duration(b) > _duration(a):
        return b, a
    return a, b


def _duration(row):
    start = datetime.combine(date.min, row.start_time)
    end = datetime.combine(date.min, row.end_time)
    return end - start


class Migration(migrations.Migration):

    dependencies = [
        ("psy_institute", "0007_leaverequest"),
    ]

    operations = [
        migrations.RunPython(dedupe_availability, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="therapistavailability",
            name="psy_availability_unique_window",
        ),
        migrations.AddConstraint(
            model_name="therapistavailability",
            constraint=models.UniqueConstraint(
                fields=("therapist", "weekday"),
                name="psy_availability_unique_weekday",
            ),
        ),
    ]
