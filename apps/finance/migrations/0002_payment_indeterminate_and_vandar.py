from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="payment",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("indeterminate", "Indeterminate"),
                    ("succeeded", "Succeeded"),
                    ("failed", "Failed"),
                    ("canceled", "Canceled"),
                ],
                db_index=True,
                default="pending",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="payment",
            name="provider",
            field=models.CharField(
                choices=[
                    ("manual", "Manual / reception"),
                    ("sep", "SEP (Saman Electronic Payment)"),
                    ("vandar", "Vandar"),
                    ("gateway", "Generic gateway"),
                ],
                default="vandar",
                max_length=16,
            ),
        ),
    ]
