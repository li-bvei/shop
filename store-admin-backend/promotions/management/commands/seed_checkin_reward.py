"""Turn on the daily "来店チェックイン" reward (a free drink voucher on the
customer's first QR scan of the day) for a chain's active campaigns.

Unlike seed_promotions_demo this is NOT DEBUG-gated — it is meant to be run
once on the server after deploying the check-in feature:

    python manage.py seed_checkin_reward --org 1
    python manage.py seed_checkin_reward --branch shinsaibashi --reward-type dessert

It is idempotent: every run just re-asserts the reward config on each
active campaign it finds. A branch with no active campaign gets a minimal
one created so the reward has somewhere to live.
"""
from django.core.management.base import BaseCommand, CommandError

from branches.models import Branch
from organizations.models import Organization

from promotions.models import Campaign, RewardType

DEFAULT_LABELS = {
    RewardType.DRINK: 'ご来店ドリンクサービス券',
    RewardType.DESSERT: 'ご来店デザートサービス券',
    RewardType.SIDE_DISH: 'ご来店小鉢サービス券',
}


class Command(BaseCommand):
    help = 'Enable the daily check-in reward (free drink/dessert voucher) on a chain\'s active campaigns.'

    def add_arguments(self, parser):
        parser.add_argument('--org', help='Organization id — every branch in it.')
        parser.add_argument('--branch', help='A single branch id.')
        parser.add_argument(
            '--reward-type', default=RewardType.DRINK,
            choices=[RewardType.DRINK, RewardType.DESSERT, RewardType.SIDE_DISH],
            help='What the check-in voucher is for (default: drink).',
        )
        parser.add_argument('--label', default=None, help='Voucher label (default: a JA phrase per reward type).')
        parser.add_argument('--expires-days', type=int, default=1, help='Voucher validity in days (default: 1).')

    def handle(self, *args, **options):
        branches = self._resolve_branches(options)
        reward_type = options['reward_type']
        label = options['label'] or DEFAULT_LABELS[reward_type]
        expires_days = max(1, options['expires_days'])

        config = {
            'checkin_reward_enabled': True,
            'checkin_reward_type': reward_type,
            'checkin_reward_config': {'label': label},
            'checkin_reward_expires_after_days': expires_days,
        }

        touched = 0
        for branch in branches:
            campaigns = list(Campaign.objects.filter(branch=branch, status=Campaign.Status.ACTIVE))
            if not campaigns:
                campaigns = [Campaign.objects.create(
                    branch=branch, name='来店チェックインキャンペーン',
                    description='seed_checkin_reward — daily check-in drink voucher',
                    status=Campaign.Status.ACTIVE, active_weekdays='1234567', priority=0,
                    **config,
                )]
                self.stdout.write(f'  {branch.id}: created campaign {campaigns[0].id}')
            else:
                for campaign in campaigns:
                    for field, value in config.items():
                        setattr(campaign, field, value)
                    campaign.save(update_fields=list(config))
                    self.stdout.write(f'  {branch.id}: updated campaign {campaign.id} ({campaign.name})')
            touched += len(campaigns)

        self.stdout.write(self.style.SUCCESS(
            f'check-in reward on: {reward_type} "{label}", {expires_days}d validity — '
            f'{touched} campaign(s) across {len(branches)} branch(es)'
        ))

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
