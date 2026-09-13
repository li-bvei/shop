from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed


class OrganizationScopedJWTAuthentication(JWTAuthentication):
    """Same as simplejwt's own authentication, plus one more check: a token
    belonging to a suspended Organization (Organization.active=False) is
    rejected on the very next request — the same immediacy the built-in
    is_active check already gives a deactivated individual account,
    extended to "the whole tenant is suspended". Platform superusers are
    exempt; their own Organization membership is incidental, not the thing
    being gated."""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if not user.is_superuser and not user.organization.active:
            raise AuthenticationFailed('organization-suspended', code='organization_suspended')
        return user
