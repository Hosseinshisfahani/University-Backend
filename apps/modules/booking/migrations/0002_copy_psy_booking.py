from django.db import migrations


def _copy(apps, schema_editor):
    Institute = apps.get_model("tenancy", "Institute")
    psy = Institute.objects.filter(slug="psy").first()
    if psy is None:
        return
    OldType = apps.get_model("psy_institute", "SessionType")
    OldProfile = apps.get_model("psy_institute", "TherapistProfile")
    OldPatient = apps.get_model("psy_institute", "PatientProfile")
    OldOffer = apps.get_model("psy_institute", "TherapistSessionOffer")
    OldAvailability = apps.get_model("psy_institute", "TherapistAvailability")
    OldException = apps.get_model("psy_institute", "AvailabilityException")
    OldLeave = apps.get_model("psy_institute", "LeaveRequest")
    OldSlot = apps.get_model("psy_institute", "AppointmentSlot")
    OldAppointment = apps.get_model("psy_institute", "Appointment")
    ServiceType = apps.get_model("booking", "ServiceType")
    Provider = apps.get_model("booking", "Provider")
    Offer = apps.get_model("booking", "ProviderServiceOffer")
    Availability = apps.get_model("booking", "ProviderAvailability")
    ExceptionRow = apps.get_model("booking", "AvailabilityException")
    Leave = apps.get_model("booking", "LeaveRequest")
    Slot = apps.get_model("booking", "Slot")
    Appointment = apps.get_model("booking", "Appointment")
    patients = dict(OldPatient.objects.values_list("id", "user_id"))
    providers = {}
    for profile in OldProfile.objects.all():
        provider, _ = Provider.objects.update_or_create(
            institute_id=psy.id,
            user_id=profile.user_id,
            defaults={
                "display_name": profile.display_name,
                "is_active": profile.is_active,
                "is_accepting": profile.is_accepting_patients,
            },
        )
        providers[profile.id] = provider.id
        OldProfile.objects.filter(pk=profile.id).update(provider_id=provider.id)
    for row in OldType.objects.all():
        ServiceType.objects.update_or_create(
            id=row.pk,
            defaults={
                "institute_id": psy.id,
                "name": row.name,
                "slug": row.slug,
                "modality": row.modality,
                "duration_minutes": row.duration_minutes,
                "price": row.price,
                "buffer_minutes": row.buffer_minutes,
                "is_active": row.is_active,
                "sort_order": row.sort_order,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            },
        )
    for row in OldOffer.objects.all():
        Offer.objects.update_or_create(
            id=row.pk,
            defaults={
                "institute_id": psy.id,
                "provider_id": providers.get(row.therapist_id),
                "service_type_id": row.session_type_id,
                "is_active": row.is_active,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            },
        )
    for row in OldAvailability.objects.all():
        Availability.objects.update_or_create(
            id=row.pk,
            defaults={
                "institute_id": psy.id,
                "provider_id": providers.get(row.therapist_id),
                "weekday": row.weekday,
                "start_time": row.start_time,
                "end_time": row.end_time,
                "timezone": row.timezone,
                "valid_from": row.valid_from,
                "valid_until": row.valid_until,
                "is_active": row.is_active,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            },
        )
    for row in OldException.objects.all():
        ExceptionRow.objects.update_or_create(
            id=row.pk,
            defaults={
                "institute_id": psy.id,
                "provider_id": providers.get(row.therapist_id),
                "date": row.date,
                "is_day_off": row.is_day_off,
                "start_time": row.start_time,
                "end_time": row.end_time,
                "reason": row.reason,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            },
        )
    for row in OldLeave.objects.all():
        Leave.objects.update_or_create(
            id=row.pk,
            defaults={
                "institute_id": psy.id,
                "provider_id": providers.get(row.therapist_id),
                "starts_on": row.starts_on,
                "ends_on": row.ends_on,
                "start_time": row.start_time,
                "end_time": row.end_time,
                "reason": row.reason,
                "status": row.status,
                "reviewed_by_id": row.reviewed_by_id,
                "reviewed_at": row.reviewed_at,
                "admin_note": row.admin_note,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            },
        )
    for row in OldSlot.objects.all():
        Slot.objects.update_or_create(
            id=row.pk,
            defaults={
                "institute_id": psy.id,
                "provider_id": providers.get(row.therapist_id),
                "service_type_id": row.session_type_id,
                "starts_at": row.starts_at,
                "ends_at": row.ends_at,
                "status": row.status,
                "generation_batch": row.generation_batch,
                "hold_expires_at": row.hold_expires_at,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            },
        )
    for row in OldAppointment.objects.all():
        Appointment.objects.update_or_create(
            id=row.pk,
            defaults={
                "institute_id": psy.id,
                "slot_id": row.slot_id,
                "customer_id": patients.get(row.patient_id),
                "provider_id": providers.get(row.therapist_id),
                "service_type_id": row.session_type_id,
                "starts_at": row.starts_at,
                "ends_at": row.ends_at,
                "status": row.status,
                "price_snapshot": row.price_snapshot,
                "payment_ref": row.payment_ref,
                "deposit_ledger_ref": row.deposit_ledger_ref,
                "canceled_at": row.canceled_at,
                "cancellation_reason": row.cancellation_reason,
                "refund_policy_applied": row.refund_policy_applied,
                "refund_ledger_ref": row.refund_ledger_ref,
                "meeting_link": row.meeting_link,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            },
        )
    Ledger = apps.get_model("finance", "LedgerEntry")
    for entry in Ledger.objects.filter(reference__startswith="psy.appointment:"):
        entry.reference = "booking.appointment:" + entry.reference.removeprefix("psy.appointment:")
        entry.save(update_fields=["reference"])


class Migration(migrations.Migration):
    dependencies = [
        ("booking", "0001_booking_scope"),
        ("psy_institute", "0020_booking_scope"),
        ("finance", "0004_shop_purchase_entry_type"),
    ]
    operations = [migrations.RunPython(_copy, migrations.RunPython.noop)]
