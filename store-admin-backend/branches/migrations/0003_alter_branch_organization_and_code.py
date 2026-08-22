import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0002_backfill_default_organization'),
        ('branches', '0002_branch_code_branch_organization_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='branch',
            name='organization',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name='branches', to='organizations.organization',
            ),
        ),
        migrations.AlterField(
            model_name='branch',
            name='code',
            field=models.SlugField(
                help_text='Unique within the Organization; may repeat across different Organizations.',
                max_length=50,
            ),
        ),
    ]
