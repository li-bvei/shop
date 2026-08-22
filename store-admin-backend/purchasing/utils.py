import re
import unicodedata


def normalize_item_name(name: str) -> str:
    """Canonicalizes surface-level text variation (full/half-width forms,
    whitespace runs, letter case) so the same product entered slightly
    differently still groups together for price comparison.

    Deliberately conservative: it never strips quantity/unit descriptors
    (e.g. '1P', '1ケース') or the supplier-name suffix some entries embed,
    because those can genuinely distinguish different SKUs — collapsing
    them would risk comparing apples to oranges.
    """
    normalized = unicodedata.normalize('NFKC', name or '')
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized.lower()


def prior_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1
