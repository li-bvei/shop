"""Shared helpers for the "past reports are locked" feature.

A report dated before today (JST) can only be created/updated if the
request carries a valid unlock token, issued by ReportUnlockView after
checking the org's shared unlock password (Organization.report_unlock_
password_hash). The token is a signed, self-contained string — no server
state — so it naturally expires and needs no session/cache row to track.
"""
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

# Not a real "session" (this API is stateless JWT), but the requested
# behaviour — unlocking should only last the current edit, not linger
# indefinitely — is well approximated by a short expiry.
UNLOCK_TOKEN_TTL_SECONDS = 30 * 60
_SALT = 'dailyreports.report_lock'


def issue_unlock_token(user) -> str:
    signer = TimestampSigner(salt=_SALT)
    return signer.sign(f'{user.organization_id}:{user.id}')


def unlock_token_is_valid(request) -> bool:
    token = request.headers.get('X-Report-Unlock-Token', '')
    if not token:
        return False
    signer = TimestampSigner(salt=_SALT)
    try:
        value = signer.unsign(token, max_age=UNLOCK_TOKEN_TTL_SECONDS)
    except (BadSignature, SignatureExpired):
        return False
    try:
        org_id, user_id = value.split(':', 1)
    except ValueError:
        return False
    return org_id == str(request.user.organization_id) and user_id == str(request.user.id)
