"""Rate limits on /api/token/ (login) — two independent dimensions, both
must pass: a per-IP ceiling (stops one source hammering many accounts) and
a per-account ceiling (stops one account being brute-forced from many
IPs/rotated proxies). Counts every attempt, successful or not — same
convention as promotions.throttling's existing throttles, and simpler than
tracking failures separately while still making sustained guessing
impractical.
"""
from rest_framework.throttling import SimpleRateThrottle

from promotions.utils import client_ip


class LoginIpThrottle(SimpleRateThrottle):
    scope = 'login_ip'

    def get_cache_key(self, request, view):
        ident = client_ip(request) or 'unknown'
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class LoginAccountThrottle(SimpleRateThrottle):
    scope = 'login_account'

    def get_cache_key(self, request, view):
        username = (request.data.get('username') or '').strip().lower()
        if not username:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': username}
