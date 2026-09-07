"""Apply the ready-made tiered lottery prize pool (promotions.prize_presets
.RICH_POOL) to a campaign — 特賞 ¥5,000 down through 金/銀/銅 coupons, a few
料理賞 (和牛 / 鮮魚 / シェフのおすすめ / 季節野菜), the 定番 drink & dessert,
and a no-lose 100-point 参加賞.

Not DEBUG-gated — meant to be run on the server after deploying. Idempotent:
matches prizes by name, so re-running keeps consumed stock; prizes not in
the preset are removed so the wheel has no stale segments.

    python manage.py seed_prize_pool --campaign 1
    python manage.py seed_prize_pool --org 1            # every active campaign in the org
    python manage.py seed_prize_pool --branch shinsaibashi
"""
from django.core.management.base import BaseCommand, CommandError

from branches.models import Branch
from organizations.models import Organization

from promotions.models import Campaign
from promotions.prize_presets import RICH_POOL, apply_prize_pool


class Command(BaseCommand):
    help = 'Apply the tiered demo lottery prize pool to a campaign / org / branch.'

    def add_arguments(self, parser):
        parser.add_argument('--campaign', type=int, help='A single campaign id.')
        parser.add_argument('--org', help='Organization id — every active campaign in it.')
        parser.add_argument('--branch', help='A single branch id — its active campaigns.')

    def handle(self, *args, **options):
        campaigns = self._resolve_campaigns(options)
        if not campaigns:
            raise CommandError('no matching campaign — pass --campaign <id>, --org <id> or --branch <id>')

        total_weight = sum(r[1] for r in RICH_POOL)
        for campaign in campaigns:
            created, updated, removed = apply_prize_pool(campaign)
            self.stdout.write(
                f'  campaign {campaign.id} ({campaign.branch_id} / {campaign.name}): '
                f'+{created} new, {updated} updated, -{removed} removed'
            )
        self.stdout.write(self.style.SUCCESS(
            f'{len(RICH_POOL)} prizes (Σweight {total_weight}) applied to {len(campaigns)} campaign(s)'
        ))

    def _resolve_campaigns(self, options):
        if options.get('campaign'):
            campaign = Campaign.objects.filter(pk=options['campaign']).first()
            if not campaign:
                raise CommandError(f'campaign-not-found: {options["campaign"]}')
            return [campaign]

        if options.get('branch'):
            if not Branch.objects.filter(id=options['branch']).exists():
                raise CommandError(f'branch-not-found: {options["branch"]}')
            return list(Campaign.objects.filter(
                branch_id=options['branch'], status=Campaign.Status.ACTIVE,
            ))

        if options.get('org'):
            if not Organization.objects.filter(id=options['org']).exists():
                raise CommandError(f'organization-not-found: {options["org"]}')
            return list(Campaign.objects.filter(
                branch__organization_id=options['org'], status=Campaign.Status.ACTIVE,
            ))

        raise CommandError('pass --campaign <id>, --org <id> or --branch <id>')
