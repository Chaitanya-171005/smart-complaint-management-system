from django.db import migrations, models
from django.db.models import Q
from django.db.models.functions import Lower
from django.core.validators import MaxValueValidator


MAX_SLA_DURATION_MINUTES = 365 * 24 * 60


def populate_sla_scope_keys(apps, schema_editor):
    SLAConfiguration = apps.get_model("routing", "SLAConfiguration")
    for config in SLAConfiguration.objects.all().iterator():
        config.scope_key = f"{config.category_id or 0}:{config.priority}"
        config.save(update_fields=["scope_key"])


class Migration(migrations.Migration):
    dependencies = [("routing", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="slaconfiguration",
            name="scope_key",
            field=models.CharField(default="", editable=False, max_length=120),
            preserve_default=False,
        ),
        migrations.RunPython(populate_sla_scope_keys, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="slaconfiguration",
            name="duration_minutes",
            field=models.PositiveIntegerField(
                validators=[MaxValueValidator(MAX_SLA_DURATION_MINUTES)]
            ),
        ),
        migrations.AddConstraint(
            model_name="category",
            constraint=models.UniqueConstraint(Lower("name"), name="category_name_ci_unique"),
        ),
        migrations.AddConstraint(
            model_name="slaconfiguration",
            constraint=models.CheckConstraint(
                condition=Q(duration_minutes__lte=MAX_SLA_DURATION_MINUTES),
                name="sla_duration_within_one_year",
            ),
        ),
        migrations.AddConstraint(
            model_name="slaconfiguration",
            constraint=models.UniqueConstraint(
                condition=Q(active=True),
                fields=("scope_key",),
                name="sla_unique_active_scope",
            ),
        ),
    ]
