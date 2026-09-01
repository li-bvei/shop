from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from branches.models import Branch

from promotions.models import Campaign, Milestone, Prize, RewardType
from promotions.services import make_store_token, register_customer, verify_spend

# 打卡与抽奖实施方案.md §6 — weights sum to 500.
DEMO_PRIZES = [
    # (name, weight, reward_type, config, total_stock, daily_stock, expiry_days, min_spend, approval)
    ('終極大奖 ¥5,000券', 1, RewardType.CASH_VOUCHER, {'face_yen': 5000, 'min_spend_yen': 6000}, None, 1, 90, 6000, True),
    ('二等奖 ¥1,000券', 5, RewardType.CASH_VOUCHER, {'face_yen': 1000, 'min_spend_yen': 3000}, None, 3, 60, 3000, False),
    ('三等奖 ¥500券', 14, RewardType.CASH_VOUCHER, {'face_yen': 500, 'min_spend_yen': 1500}, None, 10, 45, 1500, False),
    ('主厨指定料理', 15, RewardType.CHEF_SPECIAL, {'menu_value_cap_yen': 1200}, None, 5, 30, 0, False),
    ('送菜（小菜）1份', 45, RewardType.SIDE_DISH, {'label': '指定小菜 1 份'}, None, None, 30, 0, False),
    ('甜品 1份', 85, RewardType.DESSERT, {'label': 'デザート 1 品'}, None, None, 30, 0, False),
    ('饮料 1杯', 135, RewardType.DRINK, {'label': 'ソフトドリンク 1 杯'}, None, None, 30, 0, False),
    ('谢谢参与（返30积分）', 200, RewardType.POINTS_REFUND, {'points': 30}, None, None, 30, 0, False),
]

DEMO_MILESTONES = [
    (300, RewardType.DRINK, {'label': 'ドリンク 1 杯'}, 45, '300pt達成：ドリンク券'),
    (800, RewardType.DESSERT, {'label': 'デザート 1 品'}, 45, '800pt達成：デザート券'),
    (2500, RewardType.CASH_VOUCHER, {'face_yen': 500}, 60, '2500pt達成：¥500 券'),
]


class Command(BaseCommand):
    help = (
        'Idempotently seed a demo promotions campaign with the §6 prize pool '
        'and §5 milestones on the 心斋桥 branch, plus a demo customer with a '
        'little points history, for frontend integration work. DEBUG only.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--branch', default=None, help='Branch id (default: the 心斋桥 branch).')

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('development-only-command')

        branch = self._resolve_branch(options.get('branch'))

        campaign, created = Campaign.objects.get_or_create(
            branch=branch,
            name='DEMO 積分カード',
            defaults={
                'description': 'seed_promotions_demo — phase 1/2 integration campaign',
                'status': Campaign.Status.ACTIVE,
                'points_per_1000yen': 10,
                'points_per_draw': 100,
                'points_per_voucher': 100,
                'voucher_yen_per_unit': 100,
                'points_expire_months': 12,
                'max_draws_per_customer_per_day': 10,
                'direct_draw_threshold_yen': 3000,
                'stamp_target': 5,
            },
        )
        if not created and campaign.status != Campaign.Status.ACTIVE:
            campaign.status = Campaign.Status.ACTIVE
            campaign.save(update_fields=['status'])

        for order, (name, weight, rtype, config, total, daily, exp, minspend, approval) in enumerate(DEMO_PRIZES):
            Prize.objects.update_or_create(
                campaign=campaign, name=name,
                defaults={
                    'display_order': order, 'weight': weight, 'reward_type': rtype,
                    'reward_config': config, 'total_stock': total, 'remaining_stock': total,
                    'daily_stock': daily, 'voucher_expires_after_days': exp or 30,
                    'voucher_min_spend_yen': minspend, 'requires_manual_approval': approval,
                    'active': True,
                },
            )

        for threshold, rtype, config, exp, label in DEMO_MILESTONES:
            Milestone.objects.update_or_create(
                campaign=campaign, points_threshold=threshold,
                defaults={
                    'reward_type': rtype, 'reward_config': config,
                    'voucher_expires_after_days': exp, 'display_label': label, 'active': True,
                },
            )

        customer = register_customer(
            organization=branch.organization, phone='09000000001', name='デモ太郎',
            birthday_md='03-07', campaign=campaign,
        )
        if not customer.spend_verifications.exists():
            verify_spend(campaign=campaign, branch=branch, customer=customer, amount_yen=12000)
            verify_spend(campaign=campaign, branch=branch, customer=customer, amount_yen=1500)

        customer.refresh_from_db()
        token = make_store_token(campaign)
        self.stdout.write(self.style.SUCCESS(
            f'demo ready: branch={branch.id}, campaign={campaign.id} ({campaign.status}), '
            f'{campaign.prizes.count()} prizes, {campaign.milestones.count()} milestones\n'
            f'  store QR token: {token}\n'
            f'  register URL:   /pc/register?t={token}\n'
            f'  demo customer:  09000000001 / 生日 03-07 / '
            f'{customer.points_balance} pts (lifetime {customer.lifetime_points_earned}, '
            f'{customer.draw_chances} draw chances) / card_token {customer.card_token}'
        ))

    def _resolve_branch(self, branch_id):
        if branch_id:
            branch = Branch.objects.filter(id=branch_id).first()
            if not branch:
                raise CommandError(f'branch-not-found: {branch_id}')
            return branch
        branch = (
            Branch.objects.filter(code='shinsaibashi').first()
            or Branch.objects.filter(name_zh__icontains='心斋桥').first()
            or Branch.objects.order_by('id').first()
        )
        if not branch:
            raise CommandError('no-branch-found — run seed_demo_data first')
        return branch
