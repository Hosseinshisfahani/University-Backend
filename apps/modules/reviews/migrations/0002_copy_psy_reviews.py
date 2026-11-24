from django.contrib.contenttypes.models import ContentType
from django.db import connection, migrations


def _copy(apps, schema_editor):
    Institute = apps.get_model("tenancy", "Institute")
    psy = Institute.objects.get(slug="psy")
    Old = apps.get_model("psy_institute", "TherapistReview")
    Patient = apps.get_model("psy_institute", "PatientProfile")
    Therapist = apps.get_model("psy_institute", "TherapistProfile")
    New = apps.get_model("reviews", "Review")
    Context = apps.get_model("psy_institute", "PsyReviewContext")
    content_type = ContentType.objects.get_for_model(Therapist)
    for row in Old.objects.all().iterator():
        author_id = Patient.objects.values_list("user_id", flat=True).get(pk=row.patient_id)
        New.objects.update_or_create(
            id=row.pk,
            defaults={
                "institute_id": psy.pk,
                "author_id": author_id,
                "target_type_id": content_type.id,
                "target_id": row.therapist_id,
                "rating": row.rating,
                "body": row.body,
                "text_status": row.text_status,
                "reviewed_by_id": row.reviewed_by_id,
                "reviewed_at": row.reviewed_at,
                "admin_note": row.admin_note,
            },
        )
        New.objects.filter(pk=row.pk).update(
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        Context.objects.update_or_create(
            review_id=row.pk,
            defaults={
                "institute_id": psy.pk,
                "appointment_id": row.appointment_id,
                "patient_id": row.patient_id,
            },
        )

    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT setval(pg_get_serial_sequence('reviews_review', 'id'), "
                "COALESCE((SELECT MAX(id) FROM reviews_review), 1), true)"
            )


def _clear(apps, schema_editor):
    apps.get_model("psy_institute", "PsyReviewContext").objects.all().delete()
    apps.get_model("reviews", "Review").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("reviews", "0001_review_bridge"),
        ("psy_institute", "0019_review_bridge"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(_copy, _clear),
    ]
