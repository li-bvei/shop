"""Seed the 来店チェックイン ("visit and get rewarded") activity onto a
chain's active campaigns.

By default it sets up two cumulative-visit tiers:
  * 3 check-ins  -> dessert voucher
  * 5 check-ins  -> ¥100 discount voucher
each valid for 7 days. Optionally also turn on the per-day reward (a
voucher on every first scan of the day).

Not DEBUG-gated — meant to be run once on the server after deploying the
check-in feature. Idempotent: re-running just re-asserts the tiers.

    python manage.py seed_checkin_reward --org 1
    python manage.py seed_checkin_reward --branch shinsaibashi --expires-days 10
    python manage.py seed_checkin_reward --org 1 --dessert-at 3 --voucher-at 5 --voucher-yen 200
    python manage.py seed_checkin_reward --org 1 --daily-reward drink   # + a drink every day
"""
from django.core.management.base import BaseCommand, CommandError

from branches.models import Branch
from organizations.models import Organization

from promotions.models import Campaign, CheckinMilestone, RewardType

DAILY_LABELS = {
    RewardType.DRINK: 'ご来店ドリンクサービス券',
    RewardType.DESSERT: 'ご来店デザートサービス券',
    RewardType.SIDE_DISH: 'ご来店小鉢サービス券',
}


class Command(BaseCommand):
    help = 'Seed the check-in reward tiers (3 visits -> dessert, 5 visits -> ¥100 voucher) on active campaigns.'

    def add_arguments(self, parser):
        parser.add_argument('--org', help='Organization id — every branch in it.')
        parser.add_argument('--branch', help='A single branch id.')
        parser.add_argument('--expires-days', type=int, default=7, help='Voucher validity in days (default: 7).')
        parser.add_argument('--dessert-at', type=int, default=3, help='Visit count for the dessert tier (default: 3).')
        parser.add_argument('--voucher-at', type=int, default=5, help='Visit count for the cash tier (default: 5).')
        parser.add_argument('--voucher-yen', type=int, default=100, help='Face value of the cash tier (default: 100).')
        parser.add_argument(
            '--daily-reward', default=None,
            choices=[RewardType.DRINK, RewardType.DESSERT, RewardType.SIDE_DISH],
            help='Also issue this on every first scan of the day (default: off).',
        )

    def handle(self, *args, **options):
        branches = self._resolve_branches(options)
        expires = max(1, options['expires_days'])
        dessert_at = max(1, options['dessert_at'])
        voucher_at = max(1, options['voucher_at'])
        voucher_yen = max(1, options['voucher_yen'])
        daily = options['daily_reward']

        tiers = [
            (dessert_at, RewardType.DESSERT, {'label': f'{dessert_at}回来店：デザートサービス券'}, f'{dessert_at}回来店特典'),
            (voucher_at, RewardType.CASH_VOUCHER, {'face_yen': voucher_yen}, f'{voucher_at}回来店特典'),
        ]

        campaigns = self._target_campaigns(branches)
        for campaign in campaigns:
            for threshold, rtype, config, label in tiers:
                CheckinMilestone.objects.update_or_create(
                    campaign=campaign, checkin_threshold=threshold,
                    defaults={
                        'reward_type': rtype, 'reward_config': config,
                        'voucher_expires_after_days': expires, 'display_label': label, 'active': True,
                    },
                )
            # drop any tiers no longer in the seed so re-running is clean
            campaign.checkin_milestones.exclude(
                checkin_threshold__in=[t[0] for t in tiers],
            ).delete()

            if daily:
                campaign.checkin_reward_enabled = True
                campaign.checkin_reward_type = daily
                campaign.checkin_reward_config = {'label': DAILY_LABELS[daily]}
                campaign.checkin_reward_expires_after_days = expires
                campaign.save(update_fields=[
                    'checkin_reward_enabled', 'checkin_reward_type',
                    'checkin_reward_config', 'checkin_reward_expires_after_days',
                ])
            self.stdout.write(f'  {campaign.branch_id}: campaign {campaign.id} ({campaign.name})')

        self.stdout.write(self.style.SUCCESS(
            f'check-in tiers: {dessert_at}→dessert, {voucher_at}→¥{voucher_yen:,} voucher, {expires}d validity'
            + (f'; daily {daily}' if daily else '')
            + f' — {len(campaigns)} campaign(s) across {len(branches)} branch(es)'
        ))

    def _target_campaigns(self, branches):
        campaigns = []
        for branch in branches:
            active = list(Campaign.objects.filter(branch=branch, status=Campaign.Status.ACTIVE))
            if not active:
                active = [Campaign.objects.create(
                    branch=branch, name='来店チェックインキャンペーン',
                    description='seed_checkin_reward',
                    status=Campaign.Status.ACTIVE, active_weekdays='1234567', priority=0,
                )]
                self.stdout.write(f'  {branch.id}: created campaign {active[0].id}')
            campaigns.extend(active)
        return campaigns

    def _resolve_branches(self, options):
        if options.get('branch'):
            branch = Branch.objects.filter(id=options['branch']).first()
            if not branch:
                raise CommandError(f'branch-not-found: {options["branch"]}')
            return [branch]
        if options.get('org'):
            org = Organization.objects.filter(id=options['org']).first()
            if not org:
                raise CommandError(f'organization-not-found: {options["org"]}')
            branches = list(Branch.objects.filter(organization=org))
            if not branches:
                raise CommandError(f'no-branches-in-organization: {options["org"]}')
            return branches
        raise CommandError('pass --org <id> or --branch <id>')
