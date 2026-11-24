from django.db import migrations


def copy_patient_phones(apps, schema_editor):
    PatientProfile = apps.get_model("psy_institute", "PatientProfile")
    for profile in PatientProfile.objects.exclude(phone="").select_related("user"):
        user = profile.user
        if not user.phone:
            user.phone = profile.phone
            user.save(update_fields=["phone"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_user_phone"),
        ("psy_institute", "0014_clinicalreport_fileaccessrequest"),
    ]

    operations = [
        migrations.RunPython(copy_patient_phones, noop),
    ]
