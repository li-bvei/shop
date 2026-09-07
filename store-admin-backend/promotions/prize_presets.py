"""A ready-made, tiered lottery prize pool for a restaurant campaign.

The wheel is a circle, but the *value* runs in a clear ladder — 特賞 →
金/銀/銅 → 料理 → 定番 → 参加賞 — so a customer scanning the list feels
there's something real to win at every level, not just "lose / tiny prize".

Weights are relative odds (weight / Σ active weights). This pool sums to
500; ~61% of spins land a tangible prize (dish or coupon) and the rest
give 100 points back — which is itself a free re-draw, so effectively no
spin feels wasted.

Used by both `manage.py seed_prize_pool` (apply to a live campaign) and
`manage.py seed_promotions_demo`.

Also holds the default ポイント交換所 catalog (`REDEMPTION_CATALOG`) — the
items a customer buys outright with balance points.
"""
from promotions.models import Prize, RedemptionOption, RewardType

# (name, weight, reward_type, reward_config,
#  total_stock, daily_stock, voucher_expires_after_days, voucher_min_spend_yen, requires_manual_approval)
RICH_POOL = [
    # ── 特賞 / 上位賞：クーポン階段 ─────────────────────────────
    ('特賞  ¥5,000 クーポン', 1, RewardType.CASH_VOUCHER,
     {'face_yen': 5000, 'min_spend_yen': 6000}, None, 1, 90, 6000, True),
    ('金賞  ¥2,000 クーポン', 3, RewardType.CASH_VOUCHER,
     {'face_yen': 2000, 'min_spend_yen': 4000}, None, 2, 60, 4000, False),
    ('銀賞  ¥1,000 クーポン', 9, RewardType.CASH_VOUCHER,
     {'face_yen': 1000, 'min_spend_yen': 2500}, None, None, 45, 2500, False),
    ('銅賞  ¥500 クーポン', 22, RewardType.CASH_VOUCHER,
     {'face_yen': 500, 'min_spend_yen': 1500}, None, None, 45, 1500, False),

    # ── 料理賞：素材ちがいで数種類（店が用意しやすいものを選べる）──
    ('黒毛和牛の一品', 7, RewardType.CHEF_SPECIAL,
     {'menu_value_cap_yen': 2000}, None, 3, 30, 0, True),
    ('本日の鮮魚料理', 14, RewardType.CHEF_SPECIAL,
     {'menu_value_cap_yen': 1500}, None, None, 30, 0, False),
    ('シェフのおすすめ一品', 22, RewardType.CHEF_SPECIAL,
     {'menu_value_cap_yen': 1200}, None, None, 30, 0, False),
    ('季節の野菜料理（小鉢）', 35, RewardType.SIDE_DISH,
     {'label': '季節の野菜を使った小鉢 1品'}, None, None, 30, 0, False),

    # ── 定番賞：ほぼ当たる ─────────────────────────────────────
    ('本日のデザート 1品', 70, RewardType.DESSERT,
     {'label': '本日のデザート 1品'}, None, None, 30, 0, False),
    ('生ビール または ソフトドリンク 1杯', 120, RewardType.DRINK,
     {'label': '生ビール / ソフトドリンクからお選びいただけます'}, None, None, 30, 0, False),

    # ── 参加賞：ハズレなし（次回の抽選1回分）──────────────────
    ('次回使える 100 ポイント進呈', 197, RewardType.POINTS_REFUND,
     {'points': 100}, None, None, 30, 0, False),
]


def apply_prize_pool(campaign, pool=RICH_POOL):
    """Idempotently set `campaign`'s prize pool to `pool`. Matches existing
    rows by name so re-running keeps each prize's already-consumed stock;
    prizes not in `pool` are dropped so the wheel never shows a stale
    segment. Returns (created, updated, removed) counts."""
    created = updated = 0
    for order, row in enumerate(pool):
        name, weight, rtype, config, total, daily, exp, min_spend, approval = row
        existing = Prize.objects.filter(campaign=campaign, name=name).first()
        fields = {
            'display_order': order,
            'weight': weight,
            'reward_type': rtype,
            'reward_config': config,
            'total_stock': total,
            'daily_stock': daily,
            'voucher_expires_after_days': exp,
            'voucher_min_spend_yen': min_spend,
            'requires_manual_approval': approval,
            'active': True,
        }
        if existing is None:
            Prize.objects.create(campaign=campaign, name=name, remaining_stock=total, **fields)
            created += 1
        else:
            # preserve how much has already been won; re-cap remaining to
            # the new total minus what's consumed
            consumed = max(0, (existing.total_stock or 0) - (existing.remaining_stock or 0))
            fields['remaining_stock'] = None if total is None else max(0, total - consumed)
            for k, v in fields.items():
                setattr(existing, k, v)
            existing.save(update_fields=[*fields.keys()])
            updated += 1
    removed, _ = campaign.prizes.exclude(name__in=[r[0] for r in pool]).delete()
    return created, updated, removed


# The default ポイント交換所 — items bought outright with balance points.
# Saving is rewarded: ¥600 for 500pt vs ¥300 for 300pt. Drinks/desserts are
# cheap for the store to give but feel valuable, so they anchor the low end.
# (name, points_cost, reward_type, reward_config, total_stock, voucher_expires_after_days, voucher_min_spend_yen)
REDEMPTION_CATALOG = [
    ('¥100 割引券', 100, RewardType.CASH_VOUCHER, {'face_yen': 100}, None, 45, 0),
    ('ソフトドリンク 1杯', 200, RewardType.DRINK, {'label': 'ソフトドリンク 1杯'}, None, 30, 0),
    ('季節の小鉢 1品', 250, RewardType.SIDE_DISH, {'label': '季節の小鉢 1品'}, None, 30, 0),
    ('¥300 割引券', 300, RewardType.CASH_VOUCHER, {'face_yen': 300, 'min_spend_yen': 1500}, None, 45, 1500),
    ('本日のデザート 1品', 350, RewardType.DESSERT, {'label': '本日のデザート 1品'}, None, 30, 0),
    ('¥600 割引券（貯めてお得）', 500, RewardType.CASH_VOUCHER, {'face_yen': 600, 'min_spend_yen': 3000}, None, 45, 3000),
]


def apply_redemption_catalog(campaign, catalog=REDEMPTION_CATALOG):
    """Idempotently set `campaign`'s ポイント交換所 to `catalog`. Matches by
    name (keeps consumed stock); items not in `catalog` are dropped.
    Returns (created, updated, removed)."""
    created = updated = 0
    for order, row in enumerate(catalog):
        name, cost, rtype, config, total, exp, min_spend = row
        existing = RedemptionOption.objects.filter(campaign=campaign, name=name).first()
        fields = {
            'display_order': order,
            'points_cost': cost,
            'reward_type': rtype,
            'reward_config': config,
            'total_stock': total,
            'voucher_expires_after_days': exp,
            'voucher_min_spend_yen': min_spend,
            'active': True,
        }
        if existing is None:
            RedemptionOption.objects.create(
                campaign=campaign, name=name, remaining_stock=total, **fields,
            )
            created += 1
        else:
            consumed = max(0, (existing.total_stock or 0) - (existing.remaining_stock or 0))
            fields['remaining_stock'] = None if total is None else max(0, total - consumed)
            for k, v in fields.items():
                setattr(existing, k, v)
            existing.save(update_fields=[*fields.keys()])
            updated += 1
    removed, _ = campaign.redemption_options.exclude(name__in=[r[0] for r in catalog]).delete()
    return created, updated, removed
