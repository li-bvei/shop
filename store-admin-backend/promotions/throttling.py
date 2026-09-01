"""IP-scoped throttles for the public guest endpoints.

These use the shared `DatabaseCache` configured in settings (LocMemCache
would let each gunicorn worker count separately, defeating the purpose).
Rates come from settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] but no
`DEFAULT_THROTTLE_CLASSES` is set, so throttling only applies where a view
opts in via `throttle_classes`.
"""

from rest_framework.throttling import SimpleRateThrottle

from .utils import client_ip


class _IpScopedThrottle(SimpleRateThrottle):
    """Keyed on the real client IP (the proxy-appended X-Forwarded-For hop,
    see promotions.utils.client_ip), not on the authenticated user (there
    is none here)."""

    def get_cache_key(self, request, view):
        ident = client_ip(request) or 'unknown'
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class GuestReadThrottle(_IpScopedThrottle):
    """Card views / lookups — generous; a customer refreshing their card
    should never hit this."""

    scope = 'promo_guest_read'


class GuestWriteThrottle(_IpScopedThrottle):
    """Registration / points redemption / draws — the endpoints that
    actually create value. Tight enough to make scripted abuse painful,
    loose enough for a family sharing one restaurant's Wi-Fi."""

    scope = 'promo_guest_write'


class StaffVerifyThrottle(SimpleRateThrottle):
    """A ceiling on how fast one authenticated staff account can create
    spend confirmations — a real counter can't physically check people out
    faster than this, so a burst past it is worth rate-limiting even though
    the account is trusted."""

    scope = 'promo_staff_verify'

    def get_cache_key(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return None
        return self.cache_format % {'scope': self.scope, 'ident': request.user.pk}
