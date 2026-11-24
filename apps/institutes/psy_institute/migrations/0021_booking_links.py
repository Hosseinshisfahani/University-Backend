import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("booking", "0002_copy_psy_booking"),
        ("psy_institute", "0020_booking_scope"),
    ]

    operations = [
        migrations.AlterField(
            model_name="clinicalreport",
            name="appointment",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="clinical_report",
                to="booking.appointment",
                verbose_name="نوبت",
            ),
        ),
        migrations.AlterField(
            model_name="psyreviewcontext",
            name="appointment",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="review_context",
                to="booking.appointment",
                verbose_name="نوبت",
            ),
        ),
        migrations.AlterField(
            model_name="sessionnote",
            name="appointment",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="notes",
                to="booking.appointment",
                verbose_name="نوبت",
            ),
        ),
    ]
