from django.db import transaction
from rest_framework.exceptions import ValidationError

from .models import Stock, StockTransaction


def adjust_stock(*, branch, product, transaction_type, quantity, note='', operator=None):
    """The only sanctioned way to change Stock.quantity — always pairs the
    change with a StockTransaction ledger entry inside one atomic block,
    under a row lock so concurrent adjustments (e.g. two receiving clerks
    scanning the same item at once) can't race past each other and leave
    the ledger sum out of step with the cached quantity."""
    if quantity is None or quantity <= 0:
        raise ValidationError({'quantity': ['Must be greater than zero.']})

    with transaction.atomic():
        stock, _ = Stock.objects.select_for_update().get_or_create(branch=branch, product=product)
        delta = quantity if transaction_type in StockTransaction.IN_TYPES else -quantity
        new_quantity = stock.quantity + delta
        if new_quantity < 0:
            raise ValidationError({'quantity': ['Insufficient stock for this adjustment.']})
        stock.quantity = new_quantity
        stock.save(update_fields=['quantity', 'updated_at'])
        record = StockTransaction.objects.create(
            branch=branch, product=product, transaction_type=transaction_type,
            quantity=quantity, note=note, operator=operator,
        )
    return stock, record
