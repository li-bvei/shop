import re
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError


def normalize_phone(raw: str) -> str:
    """Canonicalize a Japanese phone number to a bare local-format digit
    string, e.g. '09012345678'. Only surface variation is folded — full /
    half-width digits, spaces, hyphens, parens, dots, and a +81 / 0081
    country prefix — so '(090) 1234-5678' and '+81 90 1234 5678' resolve to
    the same Customer row.

    This is NOT verification. The number is never checked for reachability
    and a well-formed but fake or borrowed number is accepted on purpose
    (打卡与抽奖实施方案.md §3). The only rejection is a value that can't
    serve as a stable key at all — the wrong number of digits for a
    Japanese line.
    """
    text = unicodedata.normalize('NFKC', raw or '').strip()
    is_international = text.startswith('+') or re.sub(r'\D', '', text).startswith('0081')
    digits = re.sub(r'\D', '', text)
    if digits.startswith('0081'):
        digits = digits[4:]
    if is_international and digits.startswith('81'):
        digits = digits[2:]
    if digits and not digits.startswith('0'):
        digits = '0' + digits
    if not (10 <= len(digits) <= 11):
        raise ValidationError({'phone': ['phone-invalid']})
    return digits


_PIN_RE = re.compile(r'^\d{6}$')
# A short blocklist of the PINs a targeted guesser tries first — cheap to
# reject, and it removes the fastest path through the 6-digit space.
_WEAK_PINS = {
    '123456', '654321', '123123', '112233', '121212', '123321',
    '789456', '159753', '147258', '102030', '111222', '696969',
}


def normalize_pin(raw: str) -> str:
    """Exactly 6 ASCII digits (full-width folded first). Empty stays empty
    — a PIN is optional. An obvious / sequential / all-same PIN is
    rejected."""
    text = unicodedata.normalize('NFKC', raw or '').strip()
    if not text:
        return ''
    if not _PIN_RE.match(text):
        raise ValidationError({'pin': ['pin-must-be-6-digits']})
    if text in _WEAK_PINS or len(set(text)) == 1:
        raise ValidationError({'pin': ['pin-too-common']})
    return text


# Days per month with no year in play — February keeps 29 so a Feb-29
# birthday is accepted.
_DAYS_IN_MONTH = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def normalize_birthday_md(raw: str) -> str:
    """'M/D', 'MM-DD', 'MM月DD日' etc. -> 'MM-DD'. Empty stays empty
    (birthday is optional). A value that isn't a real calendar month/day
    (e.g. 02-31, 04-31) is rejected."""
    text = unicodedata.normalize('NFKC', raw or '').strip()
    if not text:
        return ''
    parts = [p for p in re.split(r'[^\d]+', text.strip('　 ')) if p]
    if len(parts) != 2:
        raise ValidationError({'birthday_md': ['birthday-md-format']})
    month, day = int(parts[0]), int(parts[1])
    if not (1 <= month <= 12 and 1 <= day <= _DAYS_IN_MONTH[month - 1]):
        raise ValidationError({'birthday_md': ['birthday-md-format']})
    return f'{month:02d}-{day:02d}'


def business_local_date(dt, cutover):
    """The business day `dt` falls in, given a branch's day-rollover time.
    With a 05:00 cutover a sale at 02:00 counts toward the previous
    calendar day. `dt` is converted to Asia/Tokyo first (settings.TIME_ZONE)
    so a browser in another timezone can't shift the business day."""
    local = timezone.localtime(dt)
    shifted = local - timedelta(hours=cutover.hour, minutes=cutover.minute, seconds=cutover.second)
    return shifted.date()


def client_ip(request):
    """Source IP for the guest-endpoint throttles and the audit / risk
    trail.

    Only the hop our own reverse proxy appended to X-Forwarded-For can be
    trusted; anything to the LEFT of it is set by the caller. Reading the
    left-most entry (the old behaviour) let a client send a fresh
    `X-Forwarded-For` per request to mint a new throttle bucket every time
    and to slip past the device-based risk rules, so we count from the
    right instead.

    PROMOTIONS_TRUSTED_PROXY_COUNT = how many proxies sit in front of
    Django (default 1 = just our nginx; set 0 for a no-proxy deployment,
    which then uses REMOTE_ADDR and ignores the header entirely)."""
    proxy_count = getattr(settings, 'PROMOTIONS_TRUSTED_PROXY_COUNT', 1)
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if proxy_count and forwarded:
        hops = [p.strip() for p in forwarded.split(',') if p.strip()]
        if len(hops) >= proxy_count:
            return hops[-proxy_count]
    return request.META.get('REMOTE_ADDR') or None
