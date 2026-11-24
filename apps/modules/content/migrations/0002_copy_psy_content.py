from django.db import connection, migrations


def _file_name(value) -> str:
    if not value:
        return ""
    return getattr(value, "name", "") or ""


def _copy(apps, schema_editor):
    Institute = apps.get_model("tenancy", "Institute")
    psy = Institute.objects.get(slug="psy")
    pairs = (
        (
            "BlogPost",
            "Post",
            (
                "title",
                "slug",
                "excerpt",
                "body",
                "is_published",
                "published_at",
                "author_id",
                "created_at",
                "updated_at",
            ),
            {"cover_image": "cover_image"},
        ),
        (
            "NewsSlide",
            "NewsSlide",
            (
                "title",
                "body",
                "link_url",
                "link_label",
                "sort_order",
                "is_published",
                "created_at",
                "updated_at",
            ),
            {"image": "image"},
        ),
        (
            "SitePage",
            "SitePage",
            ("key", "title", "body", "created_at", "updated_at"),
            {},
        ),
    )
    for old_name, new_name, fields, files in pairs:
        Old = apps.get_model("psy_institute", old_name)
        New = apps.get_model("content", new_name)
        for row in Old.objects.all().iterator():
            values = {field: getattr(row, field) for field in fields}
            for target, source in files.items():
                values[target] = _file_name(getattr(row, source))
            values["institute_id"] = psy.pk
            New.objects.update_or_create(id=row.pk, defaults=values)
            New.objects.filter(pk=row.pk).update(
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            for table in ("content_post", "content_newsslide", "content_sitepage"):
                cursor.execute(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {table}), 1), true)"
                )


def _clear(apps, schema_editor):
    for name in ("Post", "NewsSlide", "SitePage"):
        apps.get_model("content", name).objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0001_initial"),
        ("psy_institute", "0017_tenancy_scope"),
    ]

    operations = [
        migrations.RunPython(_copy, _clear),
    ]
