from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from branches.models import Branch
from organizations.models import Organization
from paymentmethods.models import seed_default_payment_methods
from scheduling.services import seed_default_schedule_setting


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
        if User.objects.filter(username=options['admin_account']).exists():
            raise CommandError('admin-account-already-exists')
        if Organization.objects.filter(code=options['code']).exists():
            raise CommandError('organization-code-already-exists')
        branch_args = (options['branch_code'], options['branch_name_zh'], options['branch_name_ja'])
        if any(branch_args) and not all(branch_args):
            raise CommandError('all branch options must be supplied together')

        with transaction.atomic():
            organization = Organization.objects.create(
                code=options['code'], name_zh=options['name_zh'], name_ja=options['name_ja'],
            )
            branch = None
            if options['branch_code']:
                # Branch.id is historically global. Prefixing with tenant
                # code prevents collisions while `code` remains tenant-local.
                branch = Branch.objects.create(
                    id=f"{organization.code}-{options['branch_code']}",
                    organization=organization, code=options['branch_code'],
                    name_zh=options['branch_name_zh'], name_ja=options['branch_name_ja'],
                )
                seed_default_payment_methods(branch)
                seed_default_schedule_setting(branch)
            user = User(
                username=options['admin_account'], first_name=options['admin_account'],
                role=User.Role.ADMIN, organization=organization, branch=None,
                is_staff=False, is_superuser=False,
            )
            user.set_password(options['admin_password'])
            user.save()
        self.stdout.write(self.style.SUCCESS(
            f'provisioned organization={organization.code} admin={user.username} branch={branch or "none"}',
        ))
