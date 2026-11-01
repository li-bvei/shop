"""Identity of the sales-demo tenant.

Kept here rather than inside the management command because two unrelated
places need to agree on it: the command that builds the tenant, and
MeSerializer, which tells the frontend to show a standing "sample data"
banner. A serializer importing from a management command module would be
the wrong dependency direction.

Being demo is derived from this code, never stored on the Organization —
so no real tenant can acquire (or lose) demo status by editing a row.
"""

DEMO_ORG_CODE = 'demo-showcase'

#: Prefix carried by every display name the demo seed creates, so a
#: leftover row, or a screenshot taken during a sales call, is identifiable
#: at a glance as not real operating data.
DEMO_PREFIX = 'DEMO'


def is_demo_organization(organization) -> bool:
    return bool(organization) and organization.code == DEMO_ORG_CODE
