from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from branches.models import Branch
from organizations.models import Organization
from paymentmethods.models import seed_default_payment_methods
from purchasing.models import Supplier
from scheduling.services import seed_default_schedule_setting
from staff.models import StaffMember

TEST_PASSWORD = 'testpass123'


class ApiTestCase(TestCase):
    """Shared fixture for API tests: one Organization with two branches
    (each seeded with the standard default payment methods), one admin
    account, one branch-role account per branch, and one staff-role account
    (DEMO/TEST-prefixed, like every other fixture object here) linked to an
    employee at branch_a. `login_as()` authenticates through the real JWT
    endpoint — not `force_authenticate` — so bugs in the auth layer itself
    would still surface in these tests.

    For cross-tenant isolation tests, use `TwoOrganizationApiTestCase`
    instead — this class only ever sets up a single Organization."""

    def setUp(self):
        self.org = Organization.objects.create(
            code='test-org', name_zh='测试集团', name_ja='テストグループ',
        )
        self.branch_a = Branch.objects.create(
            id='test-branch-a', organization=self.org, code='branch-a', name_zh='测试分店A', name_ja='テスト支店A',
        )
        self.branch_b = Branch.objects.create(
            id='test-branch-b', organization=self.org, code='branch-b', name_zh='测试分店B', name_ja='テスト支店B',
        )
        seed_default_payment_methods(self.branch_a)
        seed_default_payment_methods(self.branch_b)
        seed_default_schedule_setting(self.branch_a)
        seed_default_schedule_setting(self.branch_b)

        self.admin = User.objects.create_user(
            username='test-admin', password=TEST_PASSWORD, role=User.Role.ADMIN, organization=self.org,
        )
        self.branch_a_user = User.objects.create_user(
            username='test-branch-a-user', password=TEST_PASSWORD, role=User.Role.BRANCH,
            organization=self.org, branch=self.branch_a,
        )
        self.branch_b_user = User.objects.create_user(
            username='test-branch-b-user', password=TEST_PASSWORD, role=User.Role.BRANCH,
            organization=self.org, branch=self.branch_b,
        )

        self.staff_employee = StaffMember.objects.create(
            name='DEMO/TEST staff', branch=self.branch_a, employment_type=StaffMember.EmploymentType.HOURLY,
        )
        self.staff_user = User.objects.create_user(
            username='test-staff-user', password=TEST_PASSWORD, role=User.Role.STAFF,
            organization=self.org, branch=self.branch_a, staff_member=self.staff_employee,
        )

        self.client = APIClient()

    def login_as(self, user, password=TEST_PASSWORD):
        resp = self.client.post('/api/token/', {'username': user.username, 'password': password})
        assert resp.status_code == 200, resp.content
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')

    def logout(self):
        self.client.credentials()


class TwoOrganizationApiTestCase(TestCase):
    """Fixture for cross-tenant isolation tests: two independent
    Organizations (A and B), each a full stand-in for one customer. Org A
    gets two branches (to also exercise "branch account can't see its own
    Organization's other branch" alongside the cross-Organization checks);
    Org B gets one. Every id is prefixed org-a-/org-b- so a leak is
    immediately obvious in a failure message."""

    def setUp(self):
        self.org_a = Organization.objects.create(code='org-a', name_zh='A集团', name_ja='Aグループ')
        self.org_b = Organization.objects.create(code='org-b', name_zh='B集团', name_ja='Bグループ')

        self.branch_a1 = Branch.objects.create(
            id='org-a-branch-1', organization=self.org_a, code='branch-1', name_zh='A集团1号店', name_ja='Aグループ1号店',
        )
        self.branch_a2 = Branch.objects.create(
            id='org-a-branch-2', organization=self.org_a, code='branch-2', name_zh='A集团2号店', name_ja='Aグループ2号店',
        )
        self.branch_b1 = Branch.objects.create(
            id='org-b-branch-1', organization=self.org_b, code='branch-1', name_zh='B集团1号店', name_ja='Bグループ1号店',
        )
        seed_default_payment_methods(self.branch_a1)
        seed_default_payment_methods(self.branch_a2)
        seed_default_payment_methods(self.branch_b1)
        seed_default_schedule_setting(self.branch_a1)
        seed_default_schedule_setting(self.branch_a2)
        seed_default_schedule_setting(self.branch_b1)

        self.admin_a = User.objects.create_user(
            username='org-a-admin', password=TEST_PASSWORD, role=User.Role.ADMIN, organization=self.org_a,
        )
        self.admin_b = User.objects.create_user(
            username='org-b-admin', password=TEST_PASSWORD, role=User.Role.ADMIN, organization=self.org_b,
        )
        self.branch_a1_user = User.objects.create_user(
            username='org-a-branch1-user', password=TEST_PASSWORD, role=User.Role.BRANCH,
            organization=self.org_a, branch=self.branch_a1,
        )
        self.branch_a2_user = User.objects.create_user(
            username='org-a-branch2-user', password=TEST_PASSWORD, role=User.Role.BRANCH,
            organization=self.org_a, branch=self.branch_a2,
        )
        self.branch_b1_user = User.objects.create_user(
            username='org-b-branch1-user', password=TEST_PASSWORD, role=User.Role.BRANCH,
            organization=self.org_b, branch=self.branch_b1,
        )

        self.staff_a1 = StaffMember.objects.create(
            name='A集团员工', branch=self.branch_a1, employment_type=StaffMember.EmploymentType.HOURLY,
        )
        self.staff_user_a1 = User.objects.create_user(
            username='org-a-staff-user', password=TEST_PASSWORD, role=User.Role.STAFF,
            organization=self.org_a, branch=self.branch_a1, staff_member=self.staff_a1,
        )
        self.staff_b1 = StaffMember.objects.create(
            name='B集团员工', branch=self.branch_b1, employment_type=StaffMember.EmploymentType.HOURLY,
        )

        self.supplier_a = Supplier.objects.create(organization=self.org_a, name='A集团供应商')
        self.supplier_b = Supplier.objects.create(organization=self.org_b, name='B集团供应商')

        self.client = APIClient()

    def login_as(self, user, password=TEST_PASSWORD):
        resp = self.client.post('/api/token/', {'username': user.username, 'password': password})
        assert resp.status_code == 200, resp.content
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')

    def logout(self):
        self.client.credentials()
