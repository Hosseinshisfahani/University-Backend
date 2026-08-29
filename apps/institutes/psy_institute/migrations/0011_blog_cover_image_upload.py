# Generated manually for ImageField blog cover uploads.

from django.db import migrations, models


def clear_external_cover_urls(apps, schema_editor):
    """Drop legacy URL strings that are not filesystem paths."""
    BlogPost = apps.get_model("psy_institute", "BlogPost")
    for post in BlogPost.objects.exclude(cover_image=""):
        value = post.cover_image or ""
        if value.startswith("http://") or value.startswith("https://"):
            post.cover_image = ""
            post.save(update_fields=["cover_image"])


class Migration(migrations.Migration):

    dependencies = [
        ("psy_institute", "0010_workshop_banner_image_upload"),
    ]

    operations = [
        migrations.RunPython(clear_external_cover_urls, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="blogpost",
            name="cover_image",
            field=models.ImageField(
                blank=True,
                max_length=500,
                upload_to="psy/blog/",
            ),
        ),
    ]
