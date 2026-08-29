"""
Add PostgreSQL GiST exclusion constraint to prevent overlapping active slots.

Uses SeparateDatabaseAndState / vendor checks so SQLite test databases can
migrate without btree_gist, while production PostgreSQL enforces overlap safety.
"""

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from django.db import migrations, models
from django.db.models import F, Func, Q


class TsTzRange(Func):
    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


CONSTRAINT = ExclusionConstraint(
    name="psy_slot_exclude_overlapping",
    expressions=[
        (F("therapist"), RangeOperators.EQUAL),
        (
            TsTzRange("starts_at", "ends_at", RangeBoundary()),
            RangeOperators.OVERLAPS,
        ),
    ],
    condition=Q(status__in=["open", "held", "booked"]),
)


def apply_gist(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    AppointmentSlot = apps.get_model("psy_institute", "AppointmentSlot")
    schema_editor.add_constraint(AppointmentSlot, CONSTRAINT)


def drop_gist(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    AppointmentSlot = apps.get_model("psy_institute", "AppointmentSlot")
    schema_editor.remove_constraint(AppointmentSlot, CONSTRAINT)


class Migration(migrations.Migration):
    dependencies = [
        ("psy_institute", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="appointmentslot",
                    constraint=CONSTRAINT,
                ),
            ],
            database_operations=[
                migrations.RunPython(apply_gist, drop_gist),
            ],
        ),
    ]
