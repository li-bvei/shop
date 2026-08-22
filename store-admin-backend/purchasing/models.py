from django.db import models

from .utils import normalize_item_name


class Supplier(models.Model):
    # Suppliers are shared master data *within* an Organization (any branch
    # in the same Organization can use the same supplier record) but never
    # across Organizations.
    organization = models.ForeignKey(
        'organizations.Organization', on_delete=models.PROTECT, related_name='suppliers',
    )
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=100, blank=True)
    contact = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=255, blank=True)
    # Remittance account, split into the fields a Japanese bank transfer slip
    # actually needs. Furigana readings are free text (not derived from the
    # kanji fields) since some names have more than one plausible reading and
    # only the supplier can say which one their bank has on file.
    bank_name = models.CharField(max_length=100, blank=True)
    bank_name_furigana = models.CharField(max_length=100, blank=True)
    branch_name = models.CharField(max_length=100, blank=True)
    branch_name_furigana = models.CharField(max_length=100, blank=True)
    account_type = models.CharField(max_length=20, blank=True)
    account_number = models.CharField(max_length=30, blank=True)
    account_holder_furigana = models.CharField(max_length=255, blank=True)
    note = models.TextField(blank=True)
    payable_override = models.DecimalField(
        max_digits=12, decimal_places=0, null=True, blank=True,
        help_text='Manual override for this month\'s payable; null means auto-computed from purchase records.',
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class PurchaseRecord(models.Model):
    date = models.DateField()
    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='purchase_records')
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='purchase_records')
    item_name = models.CharField(max_length=150)
    # Derived from item_name on every save (see normalize_item_name) — never
    # set directly. Used to group the same product across whitespace/width
    # variations for month-over-month price comparison and search.
    item_name_normalized = models.CharField(max_length=150, blank=True, db_index=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    amount = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-date', '-id']
        indexes = [
            models.Index(fields=['branch', 'supplier', 'item_name_normalized']),
        ]

    def __str__(self):
        return f'{self.date} {self.item_name}'

    def save(self, *args, **kwargs):
        # Amount and the normalized item name are always derived
        # server-side — never trust a client-supplied value for either.
        self.amount = self.quantity * self.unit_price
        self.item_name_normalized = normalize_item_name(self.item_name)
        super().save(*args, **kwargs)
