from django.db import models


class Product(models.Model):
    """Shared master data across all branches *within one Organization* —
    same pattern as Supplier. Stock levels are per-branch (see Stock
    below); a Product row itself carries no quantity."""

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        INACTIVE = 'inactive', 'Inactive'

    organization = models.ForeignKey(
        'organizations.Organization', on_delete=models.PROTECT, related_name='products',
    )
    # Blank allowed for items without a barcode (e.g. loose produce); when
    # present it's looked up by checkout/receiving scanner input, so it
    # only needs to be unique among the *non-blank* rows of one
    # Organization (see the partial unique constraint below).
    jan_code = models.CharField(max_length=32, blank=True, db_index=True)
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=100, blank=True)
    unit = models.CharField(max_length=20, default='个')
    selling_price = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    cost_price = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True)
    low_stock_threshold = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'jan_code'],
                condition=~models.Q(jan_code=''),
                name='unique_jan_code_per_organization',
            ),
        ]

    def __str__(self):
        return self.name


class Stock(models.Model):
    """Current on-hand quantity for one (branch, product) pair. Never
    written to directly outside `inventory.services.adjust_stock` — that
    function is what keeps this in sync with the StockTransaction ledger
    under a row lock."""

    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='stocks')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stocks')
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['branch', 'product'], name='unique_stock_per_branch_product'),
        ]

    def __str__(self):
        return f'{self.branch_id}/{self.product.name}: {self.quantity}'


class StockTransaction(models.Model):
    """Immutable ledger entry — every Stock.quantity change must be
    accompanied by exactly one of these, written in the same atomic block
    (see inventory.services.adjust_stock). Never updated or deleted once
    created; corrections go in as a new offsetting entry."""

    class TransactionType(models.TextChoices):
        PURCHASE_IN = 'purchase_in', 'Purchase In'
        SALE_OUT = 'sale_out', 'Sale Out'
        ADJUSTMENT_IN = 'adjustment_in', 'Adjustment In'
        ADJUSTMENT_OUT = 'adjustment_out', 'Adjustment Out'

    IN_TYPES = {TransactionType.PURCHASE_IN, TransactionType.ADJUSTMENT_IN}

    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='stock_transactions')
    # PROTECT, not CASCADE: a product with transaction history must be
    # deactivated (status=inactive), never deleted, or the ledger would
    # lose entries silently.
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='stock_transactions')
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    # Always positive; direction is derived from transaction_type (see
    # IN_TYPES) rather than encoded as a signed value, so the ledger reads
    # naturally ("出库 12" not "-12").
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.CharField(max_length=255, blank=True)
    operator = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_transactions',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.transaction_type} {self.quantity} {self.product.name}'
