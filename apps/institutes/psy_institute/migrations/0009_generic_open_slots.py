from django.db import migrations, models
import django.db.models.deletion


def unbind_open_inventory(apps, schema_editor):
    AppointmentSlot = apps.get_model("psy_institute", "AppointmentSlot")
    AppointmentSlot.objects.filter(status="open").update(session_type_id=None)
    seen: set[tuple[int, object, object]] = set()
    extras = []
    for row in AppointmentSlot.objects.filter(status="open").order_by("id"):
        key = (row.therapist_id, row.starts_at, row.ends_at)
        if key in seen:
            extras.append(row)
        else:
            seen.add(key)
    for row in extras:
        row.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("psy_institute", "0008_availability_unique_weekday"),
    ]

    operations = [
        migrations.AlterField(
            model_name="appointmentslot",
            name="session_type",
            field=models.ForeignKey(
                blank=True,
                help_text="Null while the slot is open inventory; set when held/booked.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="slots",
                to="psy_institute.sessiontype",
            ),
        ),
        migrations.RunPython(unbind_open_inventory, migrations.RunPython.noop),
    ]
