"""Per-organization feature modules.

A platform super admin (Django `is_superuser`) can switch a module off for
one Organization; every account in that Organization — admin, branch and
staff alike — then loses it, and hitting the API directly returns 403
`feature-disabled` so the frontend can show a "contact your administrator"
page.

Absence of an `OrganizationFeature` row means enabled, so nothing changes
for existing tenants until the operator flips something. Adding a new
gateable module is just a new entry in `FEATURE_REGISTRY` + its path
prefixes here — no migration.
"""

# key -> display names (both locales, matching the Branch/Org name_zh/name_ja
# convention — the backend never picks a display locale).
FEATURE_REGISTRY = {
    'products': {'name_zh': '商品管理', 'name_ja': '商品管理'},
    'inventory': {'name_zh': '库存管理', 'name_ja': '在庫管理'},
    'purchasing': {'name_zh': '进货管理', 'name_ja': '仕入管理'},
    'suppliers': {'name_zh': '供应商', 'name_ja': '仕入先管理'},
    'scheduling': {'name_zh': '排班管理', 'name_ja': 'シフト管理'},
    'wages': {'name_zh': '工资计算', 'name_ja': '給与計算'},
    'promotions': {'name_zh': '积分卡活动', 'name_ja': 'ポイントカード'},
    'lottery': {'name_zh': '抽奖导入', 'name_ja': '抽選インポート'},
}

# API path (relative to /api/) prefix -> feature key. The guest loyalty
# endpoints (/api/promotions/guest/...) are deliberately absent: a customer
# holding a card is never blocked by their chain's subscription state.
_PATH_FEATURE_PREFIXES = (
    ('products', 'products'),
    ('stock-transactions', 'inventory'),
    ('stock', 'inventory'),
    ('purchases', 'purchasing'),
    ('suppliers', 'suppliers'),
    ('branch-schedule-settings', 'scheduling'),
    ('schedule-periods', 'scheduling'),
    ('availability-requests', 'scheduling'),
    ('shifts', 'scheduling'),
    ('actual-work-records', 'scheduling'),
    ('wage-rules', 'wages'),
    ('wage-monthly-closings', 'wages'),
    ('wage-employee-results', 'wages'),
    ('promotions/campaigns', 'promotions'),
    ('promotions/customers', 'promotions'),
    ('promotions/spend-verifications', 'promotions'),
    ('promotions/prizes', 'promotions'),
    ('promotions/milestones', 'promotions'),
    ('promotions/checkin-milestones', 'promotions'),
    ('promotions/vouchers', 'promotions'),
    ('promotions/risk-events', 'promotions'),
    ('promotions/staff-permissions', 'promotions'),
    ('lottery/', 'lottery'),
)


def feature_for_path(path: str):
    """The feature key gating `path` (a request.path like '/api/products/3/'),
    or None if the path isn't module-gated."""
    prefix = '/api/'
    if not path.startswith(prefix):
        return None
    rest = path[len(prefix):]
    for p, feature in _PATH_FEATURE_PREFIXES:
        if rest == p or rest.startswith(p + '/'):
            return feature
    return None


def _disabled_features(organization_id) -> set:
    from organizations.models import OrganizationFeature

    if not organization_id:
        return set()
    return set(
        OrganizationFeature.objects
        .filter(organization_id=organization_id, enabled=False)
        .values_list('feature', flat=True)
    )


def org_feature_enabled(organization_id, feature: str) -> bool:
    if feature not in FEATURE_REGISTRY:
        return True
    return feature not in _disabled_features(organization_id)


def enabled_features_for_org(organization_id) -> list:
    """Ordered list of the feature keys this organization currently has."""
    disabled = _disabled_features(organization_id)
    return [key for key in FEATURE_REGISTRY if key not in disabled]


def feature_state_for_org(organization_id) -> list:
    """Every registered module + whether this org has it — for the platform
    admin UI."""
    disabled = _disabled_features(organization_id)
    return [
        {'feature': key, 'enabled': key not in disabled, **meta}
        for key, meta in FEATURE_REGISTRY.items()
    ]
