from django.db import migrations


def _copy(apps, schema_editor):
    Institute = apps.get_model("tenancy", "Institute")
    psy = Institute.objects.filter(slug="psy").first()
    if psy is None:
        return
    OldCourse = apps.get_model("psy_institute", "Workshop")
    OldSession = apps.get_model("psy_institute", "WorkshopSession")
    OldResource = apps.get_model("psy_institute", "WorkshopResource")
    OldEnrollment = apps.get_model("psy_institute", "WorkshopEnrollment")
    OldProgress = apps.get_model("psy_institute", "WorkshopSessionProgress")
    OldCertificate = apps.get_model("psy_institute", "WorkshopCertificate")
    Therapist = apps.get_model("psy_institute", "TherapistProfile")
    Patient = apps.get_model("psy_institute", "PatientProfile")
    Course = apps.get_model("lms", "Course")
    Session = apps.get_model("lms", "CourseSession")
    Resource = apps.get_model("lms", "CourseResource")
    Enrollment = apps.get_model("lms", "Enrollment")
    Progress = apps.get_model("lms", "SessionProgress")
    Certificate = apps.get_model("lms", "Certificate")
    Ledger = apps.get_model("finance", "LedgerEntry")
    instructors = dict(Therapist.objects.values_list("id", "user_id"))
    patients = dict(Patient.objects.values_list("id", "user_id"))

    for row in OldCourse.objects.all():
        values = {
            "institute_id": psy.id,
            "title": row.title,
            "slug": row.slug,
            "description": row.description,
            "body_md": row.body_md,
            "instructor_id": instructors.get(row.instructor_id),
            "capacity": row.capacity,
            "price": row.price,
            "starts_at": row.starts_at,
            "ends_at": row.ends_at,
            "banner_image": row.banner_image.name if row.banner_image else "",
            "recording_url": row.recording_url,
            "is_published": row.is_published,
            "certificate_enabled": row.certificate_enabled,
        }
        course, created = Course.objects.update_or_create(id=row.pk, defaults=values)
        if created:
            Course.objects.filter(pk=course.pk).update(
                created_at=row.created_at, updated_at=row.updated_at
            )
    for row in OldSession.objects.all():
        values = {
            "institute_id": psy.id,
            "workshop_id": row.workshop_id,
            "sort_order": row.sort_order,
            "title": row.title,
            "summary": row.summary,
            "starts_at": row.starts_at,
            "ends_at": row.ends_at,
            "meeting_url": row.meeting_url,
            "recording_url": row.recording_url,
        }
        session, created = Session.objects.update_or_create(id=row.pk, defaults=values)
        if created:
            Session.objects.filter(pk=session.pk).update(
                created_at=row.created_at, updated_at=row.updated_at
            )
    for row in OldResource.objects.all():
        values = {
            "institute_id": psy.id,
            "workshop_id": row.workshop_id,
            "session_id": row.session_id,
            "sort_order": row.sort_order,
            "title": row.title,
            "kind": row.kind,
            "file_url": row.file_url,
        }
        resource, created = Resource.objects.update_or_create(id=row.pk, defaults=values)
        if created:
            Resource.objects.filter(pk=resource.pk).update(
                created_at=row.created_at, updated_at=row.updated_at
            )
    for row in OldEnrollment.objects.all():
        values = {
            "institute_id": psy.id,
            "workshop_id": row.workshop_id,
            "user_id": patients.get(row.patient_id),
            "status": row.status,
            "price_snapshot": row.price_snapshot,
            "hold_expires_at": row.hold_expires_at,
            "payment_ref": row.payment_ref,
            "deposit_ledger_ref": row.deposit_ledger_ref,
            "refund_ledger_ref": row.refund_ledger_ref,
            "canceled_at": row.canceled_at,
            "cancellation_reason": row.cancellation_reason,
        }
        enrollment, created = Enrollment.objects.update_or_create(id=row.pk, defaults=values)
        if created:
            Enrollment.objects.filter(pk=enrollment.pk).update(
                created_at=row.created_at,
                updated_at=row.updated_at,
                enrolled_at=row.enrolled_at,
            )
    for row in OldProgress.objects.all():
        Progress.objects.update_or_create(
            id=row.pk,
            defaults={
                "enrollment_id": row.enrollment_id,
                "session_id": row.session_id,
                "completed_at": row.completed_at,
            },
        )
    for row in OldCertificate.objects.all():
        Certificate.objects.update_or_create(
            id=row.pk,
            defaults={
                "enrollment_id": row.enrollment_id,
                "issued_at": row.issued_at,
                "certificate_code": row.certificate_code,
                "file": row.file.name if row.file else "",
            },
        )
    for entry in Ledger.objects.filter(reference__startswith="psy.workshop:"):
        entry.reference = "lms.course:" + entry.reference.removeprefix("psy.workshop:")
        entry.save(update_fields=["reference"])
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        for table in (
            "lms_course",
            "lms_coursesession",
            "lms_courseresource",
            "lms_enrollment",
            "lms_sessionprogress",
            "lms_certificate",
        ):
            cursor.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 1), true)"
            )


class Migration(migrations.Migration):
    dependencies = [
        ("lms", "0001_initial"),
        ("psy_institute", "0019_review_bridge"),
        ("finance", "0004_shop_purchase_entry_type"),
    ]
    operations = [migrations.RunPython(_copy, migrations.RunPython.noop)]
