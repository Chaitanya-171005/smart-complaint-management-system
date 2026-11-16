from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workflow", "0004_b27_email_attempts")]

    operations = [
        migrations.AddField(
            model_name="notification", name="read_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
