from django.db import models


class PaymentMethodDef(models.Model):
    """Per-branch master data: which payment methods are available on that
    branch's daily report form. `protected=True` marks the auto-calculated
    cash row — the frontend never lets it be renamed or deleted, and the
    API rejects those requests too."""

    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='payment_methods')
    code = models.SlugField(max_length=50)
    custom_name = models.CharField(max_length=100, blank=True)
    i18n_key = models.CharField(max_length=100, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    protected = models.BooleanField(default=False)

    class Meta:
        ordering = ['branch_id', 'sort_order', 'code']
        constraints = [
            models.UniqueConstraint(fields=['branch', 'code'], name='unique_payment_method_code_per_branch'),
        ]

    def __str__(self):
        return self.custom_name or self.i18n_key or self.code


DEFAULT_METHOD_SPECS = [
    ('cash', 'paymentMethod.cash', 1, True),
    ('creditCard', 'paymentMethod.creditCard', 2, False),
    ('paypay', 'paymentMethod.paypay', 3, False),
    ('emoney', 'paymentMethod.emoney', 4, False),
    ('points', 'paymentMethod.points', 5, False),
    ('wechat', 'paymentMethod.wechat', 6, False),
    ('osakaCoupon', 'paymentMethod.osakaCoupon', 7, False),
    ('onCredit', 'paymentMethod.onCredit', 8, False),
]


def seed_default_payment_methods(branch):
    """The chain's standard starter lineup for a newly created branch —
    mirrors defaultMethodsFor() in the frontend's mock/paymentMethods.ts."""
    PaymentMethodDef.objects.bulk_create(
        PaymentMethodDef(
            branch=branch, code=code, i18n_key=i18n_key, sort_order=sort_order, protected=protected,
        )
        for code, i18n_key, sort_order, protected in DEFAULT_METHOD_SPECS
    )
