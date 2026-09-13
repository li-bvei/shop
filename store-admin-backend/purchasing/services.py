from collections import defaultdict
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


def compute_prior_purchase_deltas(records):
    """For each record, compares its unit_price against the immediately
    preceding purchase of the *same* (branch, supplier, item_name_normalized)
    — i.e. "vs last time we bought this", not a monthly average. This is a
    separate, deliberately simpler comparison from compute_price_comparisons
    above (which stays month-average-based for the price_change filter,
    since a straight last-purchase diff can look wildly misleading when two
    deliveries of the same item are months apart) — this one is only for the
    at-a-glance row hint the user actually watches day to day.

    One bulk query bounded to the groups actually present in `records`
    (never one query per record — see compute_price_comparisons for why
    that matters at this table's size), then the "previous" row within each
    group is found by walking the group in (date, id) order in Python.

    Returns {record.id: {'prior_unit_price', 'direction', 'delta_amount',
    'delta_percent'}}. A record with no prior purchase, or whose price is
    unchanged from it, is simply absent — same "absent means no comparison"
    convention as compute_price_comparisons.
    """
    records = list(records)
    if not records:
        return {}

    keys = {(r.branch_id, r.supplier_id, r.item_name_normalized) for r in records}
    query = Q()
    for branch_id, supplier_id, item_name_normalized in keys:
        query |= Q(branch_id=branch_id, supplier_id=supplier_id, item_name_normalized=item_name_normalized)

    groups = defaultdict(list)
    for row in PurchaseRecord.objects.filter(query).values(
        'id', 'branch_id', 'supplier_id', 'item_name_normalized', 'date', 'unit_price',
    ).order_by('date', 'id'):
        key = (row['branch_id'], row['supplier_id'], row['item_name_normalized'])
        groups[key].append(row)

    result = {}
    for r in records:
        group = groups.get((r.branch_id, r.supplier_id, r.item_name_normalized), [])
        prior = None
        for row in group:
            if (row['date'], row['id']) >= (r.date, r.id):
                break
            prior = row
        if prior is None or prior['unit_price'] == r.unit_price:
            continue
        prior_price = prior['unit_price']
        delta = r.unit_price - prior_price
        percent = None if prior_price == 0 else (delta / prior_price * Decimal('100')).quantize(
            Decimal('0.1'), rounding=ROUND_HALF_UP,
        )
        result[r.id] = {
            'prior_unit_price': prior_price,
            'direction': 'up' if delta > 0 else 'down',
            'delta_amount': delta,
            'delta_percent': percent,
        }
    return result
