from django.core.management.base import BaseCommand, CommandError

from organizations.services import ProvisionError, provision_organization


class Command(BaseCommand):
    help = 'Atomically provision an Organization and its first business admin.'

    def add_arguments(self, parser):
        parser.add_argument('--code', required=True)
        parser.add_argument('--name-zh', required=True)
        parser.add_argument('--name-ja', required=True)
        parser.add_argument('--admin-account', required=True)
        parser.add_argument('--admin-password', required=True)
        parser.add_argument('--branch-code')
        parser.add_argument('--branch-name-zh')
        parser.add_argument('--branch-name-ja')

    def handle(self, *args, **options):
        try:
            organization, branch, admin = provision_organization(
                code=options['code'], name_zh=options['name_zh'], name_ja=options['name_ja'],
                admin_account=options['admin_account'], admin_password=options['admin_password'],
                branch_code=options['branch_code'], branch_name_zh=options['branch_name_zh'],
                branch_name_ja=options['branch_name_ja'],
            )
        except ProvisionError as exc:
            raise CommandError(str(exc))

        self.stdout.write(self.style.SUCCESS(
            f'provisioned organization={organization.code} admin={admin.username} branch={branch or "none"}',
        ))
