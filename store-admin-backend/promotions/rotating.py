"""Time-based codes for the in-store check-in display.

The printed store QR is a static token — good enough to *register*, but a
customer can photograph it once and self-"check in" from home forever. When
a campaign turns on `checkin_requires_live_qr`, a check-in must also carry a
short code that changes every 30s. Only a screen that knows the campaign's
`checkin_secret` can produce it (`/checkin-display.html` does the same maths
in the browser, fully offline), so a photo goes stale within a minute.

Not a MAC in the cryptographic sense and it doesn't need to be: the secret
is 256 bits, the code is a truncated SHA-256 over `secret.window`, and the
only thing riding on it is one loyalty stamp. Keep this in lockstep with the
`rollCode()` function in `store-admin-frontend/public/checkin-display.html`.
"""

from __future__ import annotations

import hashlib
import hmac
import time

STEP_SECONDS = 30
CODE_LENGTH = 12  # hex chars → 48 bits; forging one is 2**-48 per throttled try

# How many past windows still count. 3 → a code stays valid ~90-120s after it
# was shown, which covers a slow scan, a walk back to the table and a display
# clock that drifts a little. +1 future window forgives a display running fast.
PAST_WINDOWS = 3
FUTURE_WINDOWS = 1


def current_window(now: float | None = None) -> int:
    return int((now if now is not None else time.time()) // STEP_SECONDS)


def make_setup_blob(*, store_token: str, secret: str, brand_name: str, origin: str = '') -> str:
    """The one string a manager pastes into /checkin-display.html to arm an
    in-store screen: the store token it embeds in every QR, the secret it
    rolls codes from, the shop name to show, and the site origin the QR
    should point at (so the display works even opened from a cached copy).
    base64url of compact JSON — opaque enough that it doesn't invite
    fiddling, not encryption."""
    import base64
    import json

    payload = json.dumps(
        {'t': store_token, 's': secret, 'n': brand_name, 'o': origin, 'step': STEP_SECONDS},
        separators=(',', ':'),
    )
    return base64.urlsafe_b64encode(payload.encode()).decode()


def code_for(secret: str, window: int) -> str:
    return hashlib.sha256(f'{secret}.{window}'.encode()).hexdigest()[:CODE_LENGTH]


def verify(secret: str, window, code: str, *, now: float | None = None) -> bool:
    """True when `code` is what `secret` produces for `window`, and `window`
    is close enough to now. Both a missing secret and a malformed window are
    a plain False, never an exception — the caller decides what a failure
    means (reject, or just don't count the stamp)."""
    if not secret or not code:
        return False
    try:
        window = int(window)
    except (TypeError, ValueError):
        return False

    here = current_window(now)
    if window > here + FUTURE_WINDOWS or window < here - PAST_WINDOWS:
        return False
    # constant-time compare; the value isn't that sensitive but it's free
    return hmac.compare_digest(code_for(secret, window), str(code))
