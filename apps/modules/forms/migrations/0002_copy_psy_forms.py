from django.db import connection, migrations


def _copy(apps, schema_editor):
    Institute = apps.get_model("tenancy", "Institute")
    psy = Institute.objects.get(slug="psy")
    OldForm = apps.get_model("psy_institute", "PsychometricForm")
    OldResponse = apps.get_model("psy_institute", "PsychometricResponse")
    Patient = apps.get_model("psy_institute", "PatientProfile")
    Therapist = apps.get_model("psy_institute", "TherapistProfile")
    Form = apps.get_model("forms", "Form")
    Version = apps.get_model("forms", "FormVersion")
    Response = apps.get_model("forms", "Response")

    for row in OldForm.objects.all().iterator():
        Form.objects.update_or_create(
            id=row.pk,
            defaults={
                "institute_id": psy.pk,
                "title": row.title,
                "slug": row.slug,
                "description": row.description,
                "schema": row.schema,
                "version": row.version,
                "is_published": row.is_published,
                "created_by_id": row.created_by_id,
            },
        )
        Form.objects.filter(pk=row.pk).update(
            created_at=row.created_at, updated_at=row.updated_at
        )
        Version.objects.get_or_create(
            form_id=row.pk,
            version=row.version,
            defaults={"schema": row.schema, "schema_available": True},
        )

    for row in OldResponse.objects.all().iterator():
        version, _ = Version.objects.get_or_create(
            form_id=row.form_id,
            version=row.form_version,
            defaults={"schema": {}, "schema_available": False},
        )
        respondent_id = Patient.objects.values_list("user_id", flat=True).get(pk=row.patient_id)
        assigned_id = None
        if row.routed_therapist_id:
            assigned_id = Therapist.objects.values_list("user_id", flat=True).get(
                pk=row.routed_therapist_id
            )
        Response.objects.update_or_create(
            id=row.pk,
            defaults={
                "institute_id": psy.pk,
                "form_id": row.form_id,
                "version_id": version.pk,
                "respondent_id": respondent_id,
                "answers": row.answers,
                "status": row.status,
                "assigned_to_id": assigned_id,
                "reviewer_notes": row.reviewer_notes,
                "score": {},
            },
        )
        Response.objects.filter(pk=row.pk).update(
            created_at=row.created_at,
            updated_at=row.updated_at,
            submitted_at=row.submitted_at,
        )

    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            for table in ("forms_form", "forms_response"):
                cursor.execute(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {table}), 1), true)"
                )


def _clear(apps, schema_editor):
    apps.get_model("forms", "Response").objects.all().delete()
    apps.get_model("forms", "FormVersion").objects.all().delete()
    apps.get_model("forms", "Form").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("forms", "0001_initial"),
        ("psy_institute", "0019_review_bridge"),
    ]

    operations = [
        migrations.RunPython(_copy, _clear),
    ]
