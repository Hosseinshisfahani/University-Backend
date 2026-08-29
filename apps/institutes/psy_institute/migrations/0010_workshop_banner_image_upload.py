# Generated manually for ImageField banner uploads.

from django.db import migrations, models


def clear_external_banner_urls(apps, schema_editor):
    """Drop legacy URL strings that are not filesystem paths."""
    Workshop = apps.get_model("psy_institute", "Workshop")
    for workshop in Workshop.objects.exclude(banner_image=""):
        value = workshop.banner_image or ""
        if value.startswith("http://") or value.startswith("https://"):
            workshop.banner_image = ""
            workshop.save(update_fields=["banner_image"])


class Migration(migrations.Migration):

    dependencies = [
        ("psy_institute", "0009_generic_open_slots"),
    ]

    operations = [
        migrations.RunPython(clear_external_banner_urls, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="workshop",
            name="banner_image",
            field=models.ImageField(
                blank=True,
                max_length=500,
                upload_to="psy/workshops/",
            ),
        ),
    ]
