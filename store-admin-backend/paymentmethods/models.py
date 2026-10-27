from django.db import models


# A method whose daily-report amount is never typed in: it is the previous
# report's cash shortfall, filled in server-side (see
# dailyreports.models.DailyReport.save). Recognised by this flag, which is set
# on creation for a row named like PREVIOUS_SHORTAGE_NAMES (the chain's
# existing hand-made "昨日不足分" row) or seeded for new branches.
AUTO_PREVIOUS_SHORTAGE = 'previous_shortage'
PREVIOUS_SHORTAGE_NAMES = {'昨日不足分'}


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
    # "Deleting" a payment method used to hard-delete this row — but old
    # DailyReport.payment_amounts blobs keep referencing its id forever, and
    # a hard delete meant that id could never be resolved back to a name
    # again (monthly/yearly reports would show the bare numeric id, which
    # is exactly what looked like a mystery/broken payment method). Deleting
    # now just flips this to False instead: gone from the entry form and
    # the branch's active list, but still resolvable by id everywhere that
    # looks up historical amounts (dashboard/analysis.py in particular).
    active = models.BooleanField(default=True)
    # '' for an ordinary hand-entered method; AUTO_PREVIOUS_SHORTAGE for the
    # auto-calculated 昨日不足分 row (amount comes from the previous day).
    auto_source = models.CharField(max_length=30, blank=True, default='')

    class Meta:
        ordering = ['branch_id', 'sort_order', 'code']
        constraints = [
            models.UniqueConstraint(fields=['branch', 'code'], name='unique_payment_method_code_per_branch'),
        ]

    def __str__(self):
        return self.custom_name or self.i18n_key or self.code

    def save(self, *args, **kwargs):
        if self._state.adding and not self.auto_source and self.custom_name.strip() in PREVIOUS_SHORTAGE_NAMES:
            self.auto_source = AUTO_PREVIOUS_SHORTAGE
        super().save(*args, **kwargs)


DEFAULT_METHOD_SPECS = [
    ('cash', 'paymentMethod.cash', 1, True),
    ('creditCard', 'paymentMethod.creditCard', 2, False),
    ('paypay', 'paymentMethod.paypay', 3, False),
    ('emoney', 'paymentMethod.emoney', 4, False),
    ('points', 'paymentMethod.points', 5, False),
    ('wechat', 'paymentMethod.wechat', 6, False),
    ('osakaCoupon', 'paymentMethod.osakaCoupon', 7, False),
    ('onCredit', 'paymentMethod.onCredit', 8, False),
    ('previousShortage', 'paymentMethod.previousShortage', 9, False),
]

_AUTO_SOURCE_BY_CODE = {'previousShortage': AUTO_PREVIOUS_SHORTAGE}


def seed_default_payment_methods(branch):
    """The chain's standard starter lineup for a newly created branch —
    mirrors defaultMethodsFor() in the frontend's mock/paymentMethods.ts."""
    PaymentMethodDef.objects.bulk_create(
        PaymentMethodDef(
            branch=branch, code=code, i18n_key=i18n_key, sort_order=sort_order, protected=protected,
            auto_source=_AUTO_SOURCE_BY_CODE.get(code, ''),
        )
        for code, i18n_key, sort_order, protected in DEFAULT_METHOD_SPECS
    )
