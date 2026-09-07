"""Apply the ready-made point-spend reward set to a campaign:

  * the tiered lottery wheel (promotions.prize_presets.RICH_POOL) — 特賞
    ¥5,000 through 金/銀/銅 coupons, 料理賞 (和牛 / 鮮魚 / シェフ / 野菜),
    定番 drink & dessert, a no-lose 100-point 参加賞
  * the ポイント交換所 catalog (REDEMPTION_CATALOG) — ¥100 / ¥300 / ¥600
    coupons, drink, side dish, dessert bought outright with balance points

Not DEBUG-gated — run on the server after deploying. Idempotent: matches by
name, keeps consumed stock, drops rows no longer in the preset. Pass
--catalog-only / --wheel-only to apply just one.

    python manage.py seed_prize_pool --campaign 1
    python manage.py seed_prize_pool --org 1            # every active campaign in the org
    python manage.py seed_prize_pool --branch shinsaibashi --catalog-only
"""
from django.core.management.base import BaseCommand, CommandError

from branches.models import Branch
from organizations.models import Organization

from promotions.models import Campaign
from promotions.prize_presets import (
    REDEMPTION_CATALOG, RICH_POOL, apply_prize_pool, apply_redemption_catalog,
)


class Command(BaseCommand):
    help = 'Apply the demo lottery wheel + ポイント交換所 catalog to a campaign / org / branch.'

    def add_arguments(self, parser):
        parser.add_argument('--campaign', type=int, help='A single campaign id.')
        parser.add_argument('--org', help='Organization id — every active campaign in it.')
        parser.add_argument('--branch', help='A single branch id — its active campaigns.')
        parser.add_argument('--wheel-only', action='store_true', help='Only the lottery wheel.')
        parser.add_argument('--catalog-only', action='store_true', help='Only the 交換所 catalog.')

    def handle(self, *args, **options):
        if options['wheel_only'] and options['catalog_only']:
            raise CommandError('--wheel-only and --catalog-only are mutually exclusive')
        do_wheel = not options['catalog_only']
        do_catalog = not options['wheel_only']

        campaigns = self._resolve_campaigns(options)
        if not campaigns:
            raise CommandError('no matching campaign — pass --campaign <id>, --org <id> or --branch <id>')

        for campaign in campaigns:
            tag = f'  campaign {campaign.id} ({campaign.branch_id} / {campaign.name}):'
            if do_wheel:
                c, u, r = apply_prize_pool(campaign)
                self.stdout.write(f'{tag} wheel +{c}/{u}/-{r}')
            if do_catalog:
                c, u, r = apply_redemption_catalog(campaign)
                self.stdout.write(f'{tag} 交換所 +{c}/{u}/-{r}')
        parts = []
        if do_wheel:
            parts.append(f'{len(RICH_POOL)} prizes (Σweight {sum(p[1] for p in RICH_POOL)})')
        if do_catalog:
            parts.append(f'{len(REDEMPTION_CATALOG)} 交換所 items')
        self.stdout.write(self.style.SUCCESS(
            f'{" + ".join(parts)} applied to {len(campaigns)} campaign(s)'
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
