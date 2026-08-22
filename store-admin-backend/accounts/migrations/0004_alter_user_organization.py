import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0002_backfill_default_organization'),
        ('accounts', '0003_user_organization'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='organization',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name='users', to='organizations.organization',
            ),
        ),
    ]
