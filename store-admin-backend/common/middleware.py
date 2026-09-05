"""Per-organization feature gate.

One place that blocks a whole module for a tenant whose platform super
admin has switched it off. Runs only for the module-gated API prefixes
(see common.features); everything else — auth, dashboards, daily reports,
the guest loyalty pages — is untouched.

It authenticates the JWT itself (DRF's own auth runs later, inside the
view) so it can read the caller's Organization. A missing/invalid token is
left alone here — the view's normal 401 handling deals with it.
"""
import json

from django.http import HttpResponse

from .features import feature_for_path, org_feature_enabled


class OrganizationFeatureGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        feature = feature_for_path(request.path)
        if feature:
            organization_id = self._organization_id(request)
            if organization_id and not org_feature_enabled(organization_id, feature):
                return HttpResponse(
                    json.dumps({'detail': 'feature-disabled', 'feature': feature}),
                    status=403,
                    content_type='application/json',
                )
        return self.get_response(request)

    @staticmethod
    def _organization_id(request):
        from rest_framework_simplejwt.authentication import JWTAuthentication
        from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

        try:
            result = JWTAuthentication().authenticate(request)
        except (InvalidToken, TokenError):
            return None
        if not result:
            return None
        user, _token = result
        return getattr(user, 'organization_id', None)
