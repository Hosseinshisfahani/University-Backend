"""Point existing therapist-profile reviews at the booking provider."""

from django.db import migrations


def retarget(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Review = apps.get_model("reviews", "Review")
    Profile = apps.get_model("psy_institute", "TherapistProfile")
    profile_type = ContentType.objects.filter(
        app_label="psy_institute", model="therapistprofile"
    ).first()
    provider_type = ContentType.objects.filter(app_label="booking", model="provider").first()
    if profile_type is None or provider_type is None:
        return
    for review in Review.objects.filter(target_type=profile_type):
        profile = Profile.objects.filter(pk=review.target_id).first()
        if profile is None or not profile.provider_id:
            continue
        review.target_type = provider_type
        review.target_id = profile.provider_id
        review.save(update_fields=["target_type", "target_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("reviews", "0002_copy_psy_reviews"),
        ("booking", "0002_copy_psy_booking"),
        ("psy_institute", "0021_booking_links"),
    ]

    operations = [
        migrations.RunPython(retarget, migrations.RunPython.noop),
    ]
