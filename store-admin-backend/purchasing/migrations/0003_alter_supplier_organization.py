import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0002_backfill_default_organization'),
        ('purchasing', '0002_supplier_organization'),
    ]

    operations = [
        migrations.AlterField(
            model_name='supplier',
            name='organization',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name='suppliers', to='organizations.organization',
            ),
        ),
    ]
