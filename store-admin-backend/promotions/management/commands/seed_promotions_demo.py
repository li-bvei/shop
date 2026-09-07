from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from branches.models import Branch

from promotions.models import Campaign, Milestone, RewardType
from promotions.prize_presets import apply_prize_pool
from promotions.services import make_store_token, register_customer, verify_spend

# Milestones fire on lifetime (cumulative) points and don't consume the
# balance — a "the more you've spent with us, the more we thank you" bonus
# on top of the 1% base earn (10pt / ¥1,000). Kept reachable: a regular
# clears the top tier in a few months, and each tier is ~1% extra back.
DEMO_MILESTONES = [
    (150, RewardType.DRINK, {'label': 'ドリンク 1杯'}, 45, '150pt達成：ドリンク券'),
    (500, RewardType.DESSERT, {'label': 'デザート 1品'}, 45, '500pt達成：デザート券'),
    (1200, RewardType.CASH_VOUCHER, {'face_yen': 1500}, 60, '1,200pt達成：¥1,500 クーポン'),
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

        # The economy the demo is calibrated around: 10pt / ¥1,000 = 1% base
        # earn, 1pt ≈ ¥1 (100pt → ¥100 voucher / draw). The milestone ¥
        # figures in the response below assume this rate — re-assert it every
        # run so a campaign left mid-tweak from an earlier session doesn't
        # quietly drift (e.g. to 20pt and half the implied spend).
        ECONOMY = {
            'status': Campaign.Status.ACTIVE,
            'points_per_1000yen': 10,
            'points_per_draw': 100,
            'points_per_voucher': 100,
            'voucher_yen_per_unit': 100,
            'points_expire_months': 12,
            'max_draws_per_customer_per_day': 10,
            'direct_draw_threshold_yen': 3000,
            'stamp_target': 5,
        }
        campaign, created = Campaign.objects.get_or_create(
            branch=branch, name='DEMO 積分カード',
            defaults={'description': 'seed_promotions_demo — phase 1/2 integration campaign', **ECONOMY},
        )
        if not created:
            for field, value in ECONOMY.items():
                setattr(campaign, field, value)
            campaign.save(update_fields=list(ECONOMY))

        # The tiered lottery pool (特賞 ¥5,000 … 料理賞 … 参加賞). Shared with
        # `manage.py seed_prize_pool`; matched by name so re-running keeps
        # consumed stock and drops prizes no longer in the preset.
        apply_prize_pool(campaign)

        for threshold, rtype, config, exp, label in DEMO_MILESTONES:
            Milestone.objects.update_or_create(
                campaign=campaign, points_threshold=threshold,
                defaults={
                    'reward_type': rtype, 'reward_config': config,
                    'voucher_expires_after_days': exp, 'display_label': label, 'active': True,
                },
            )
        campaign.milestones.exclude(points_threshold__in=[m[0] for m in DEMO_MILESTONES]).delete()

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
