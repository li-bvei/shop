from django.db import migrations, models

AUTO_PREVIOUS_SHORTAGE = 'previous_shortage'
PREVIOUS_SHORTAGE_NAMES = {'昨日不足分'}


def flag_existing_rows(apps, schema_editor):
    """The chain's hand-made "昨日不足分" rows become the auto-calculated one."""
    PaymentMethodDef = apps.get_model('paymentmethods', 'PaymentMethodDef')
    for method in PaymentMethodDef.objects.filter(protected=False):
        if method.custom_name.strip() in PREVIOUS_SHORTAGE_NAMES:
            method.auto_source = AUTO_PREVIOUS_SHORTAGE
            method.save(update_fields=['auto_source'])


class Migration(migrations.Migration):

    dependencies = [
        ('paymentmethods', '0002_paymentmethoddef_active'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymentmethoddef',
            name='auto_source',
            field=models.CharField(blank=True, default='', max_length=30),
        ),
        migrations.RunPython(flag_existing_rows, migrations.RunPython.noop),
    ]
