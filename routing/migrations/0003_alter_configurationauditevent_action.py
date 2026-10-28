from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("routing", "0002_configuration_integrity")]

    operations = [
        migrations.AlterField(
            model_name="configurationauditevent",
            name="action",
            field=models.CharField(
                choices=[
                    ("CREATED", "Created"),
                    ("UPDATED", "Updated"),
                    ("DEACTIVATED", "Deactivated"),
                    ("REACTIVATED", "Reactivated"),
                ],
                max_length=16,
            ),
        ),
    ]
