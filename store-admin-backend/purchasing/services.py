from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Avg, Q

from .models import PurchaseRecord
from .utils import prior_month


def compute_price_comparisons(records):
    """For each record, compares its unit_price against the average
    unit_price of the *same* (branch, supplier, item_name_normalized) in the
    calendar month immediately before the record's own month.

    Deliberately scoped this way, not "the last time it was bought
    whenever that was" — comparing against a stale, possibly year-old
    price would be misleading, and comparing against a different
    supplier's price for a similarly-named item would be meaningless.

    Returns {record.id: {'direction': 'up'|'down'|'same', 'prior_avg': Decimal}}.
    Records with no prior-month data are simply absent from the result —
    callers must treat "absent" as "no comparison available", never as a
    flag in either direction.
    """
    records = list(records)
    if not records:
        return {}

    lookup_keys = {
        (r.branch_id, r.supplier_id, r.item_name_normalized, *prior_month(r.date.year, r.date.month))
        for r in records
    }

    query = Q()
    for branch_id, supplier_id, item_name_normalized, py, pm in lookup_keys:
        query |= Q(
            branch_id=branch_id, supplier_id=supplier_id, item_name_normalized=item_name_normalized,
            date__year=py, date__month=pm,
        )

    prior_averages = {}
    if query:
        rows = (
            PurchaseRecord.objects.filter(query)
            .values('branch_id', 'supplier_id', 'item_name_normalized', 'date__year', 'date__month')
            .annotate(avg_price=Avg('unit_price'))
        )
        for row in rows:
            key = (
                row['branch_id'], row['supplier_id'], row['item_name_normalized'],
                row['date__year'], row['date__month'],
            )
            prior_averages[key] = row['avg_price']

    result = {}
    for r in records:
        py, pm = prior_month(r.date.year, r.date.month)
        key = (r.branch_id, r.supplier_id, r.item_name_normalized, py, pm)
        avg = prior_averages.get(key)
        if avg is None:
            continue
        if r.unit_price > avg:
            direction = 'up'
        elif r.unit_price < avg:
            direction = 'down'
        else:
            direction = 'same'
        delta = r.unit_price - avg
        percent = None if avg == 0 else (delta / avg * Decimal('100')).quantize(
            Decimal('0.1'), rounding=ROUND_HALF_UP,
        )
        result[r.id] = {
            'direction': direction, 'prior_avg': avg,
            'delta_amount': delta, 'delta_percent': percent,
        }
    return result
