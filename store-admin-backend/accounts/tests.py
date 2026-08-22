from common.test_utils import TEST_PASSWORD, ApiTestCase
from staff.models import StaffMember

from .models import User, UserPreference


class LoginTests(ApiTestCase):
    def test_admin_login_returns_correct_role_and_branch(self):
        self.login_as(self.admin)
        resp = self.client.get('/api/auth/me/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['role'], 'admin')
        self.assertIsNone(resp.data['branchId'])

    def test_branch_login_returns_correct_role_and_branch(self):
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/auth/me/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['role'], 'branch')
        self.assertEqual(resp.data['branchId'], self.branch_a.id)

    def test_wrong_password_rejected(self):
        resp = self.client.post('/api/token/', {'username': self.admin.username, 'password': 'wrong'})
        self.assertEqual(resp.status_code, 401)

    def test_me_requires_authentication(self):
        resp = self.client.get('/api/auth/me/')
        self.assertEqual(resp.status_code, 401)


class ChangePasswordTests(ApiTestCase):
    def test_self_service_change_password(self):
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/auth/change-password/', {
            'old_password': TEST_PASSWORD, 'new_password': 'newpass456',
        })
        self.assertEqual(resp.status_code, 200)
        self.branch_a_user.refresh_from_db()
        self.assertTrue(self.branch_a_user.check_password('newpass456'))

    def test_wrong_old_password_rejected(self):
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/auth/change-password/', {
            'old_password': 'not-the-real-password', 'new_password': 'newpass456',
        })
        self.assertEqual(resp.status_code, 400)
        self.branch_a_user.refresh_from_db()
        self.assertTrue(self.branch_a_user.check_password(TEST_PASSWORD))


class PreferenceTests(ApiTestCase):
    def test_unauthenticated_rejected(self):
        resp = self.client.get('/api/auth/preference/')
        self.assertEqual(resp.status_code, 401)

    def test_lazily_created_with_defaults(self):
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/auth/preference/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['locale'], 'zh')
        self.assertEqual(resp.data['theme'], 'light')

    def test_patch_persists(self):
        self.login_as(self.branch_a_user)
        resp = self.client.patch('/api/auth/preference/', {'locale': 'ja', 'theme': 'dark'}, format='json')
        self.assertEqual(resp.status_code, 200)
        pref = UserPreference.objects.get(user=self.branch_a_user)
        self.assertEqual(pref.locale, 'ja')
        self.assertEqual(pref.theme, 'dark')

    def test_preferences_are_isolated_per_account(self):
        self.login_as(self.branch_a_user)
        self.client.patch('/api/auth/preference/', {'theme': 'dark'}, format='json')

        self.login_as(self.branch_b_user)
        resp = self.client.get('/api/auth/preference/')
        self.assertEqual(resp.data['theme'], 'light')

    def test_cannot_read_another_accounts_preference_by_switching_user(self):
        # There is no id in the URL to tamper with — the endpoint always
        # resolves to request.user — but this pins that design down so a
        # future refactor into a ViewSet+pk can't silently regress it.
        self.login_as(self.branch_a_user)
        self.client.patch('/api/auth/preference/', {'locale': 'ja'}, format='json')
        self.login_as(self.admin)
        resp = self.client.get('/api/auth/preference/')
        self.assertEqual(resp.data['locale'], 'zh')


class UserViewSetTests(ApiTestCase):
    def test_branch_role_cannot_list_users(self):
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/users/')
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_list_users(self):
        self.login_as(self.admin)
        resp = self.client.get('/api/users/')
        self.assertEqual(resp.status_code, 200)

    def test_cannot_delete_self(self):
        self.login_as(self.admin)
        resp = self.client.delete(f'/api/users/{self.admin.id}/')
        self.assertEqual(resp.status_code, 400)

    def test_deleting_a_non_last_admin_succeeds(self):
        second_admin = User.objects.create_user(
            username='test-admin-2', password=TEST_PASSWORD, role=User.Role.ADMIN, organization=self.org,
        )
        self.login_as(self.admin)
        resp = self.client.delete(f'/api/users/{second_admin.id}/')
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(User.objects.filter(role=User.Role.ADMIN).count(), 1)


class StaffAccountCreationTests(ApiTestCase):
    def test_admin_can_create_staff_account_linked_to_employee(self):
        employee = StaffMember.objects.create(name='新员工', branch=self.branch_a)
        self.login_as(self.admin)
        resp = self.client.post('/api/users/', {
            'account': 'newstaff01', 'password': 'newpass123', 'displayName': '新员工',
            'role': 'staff', 'staffMemberId': employee.id,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        # Branch is derived from the employee, never independently chosen.
        self.assertEqual(resp.data['branchId'], self.branch_a.id)
        created = User.objects.get(username='newstaff01')
        self.assertEqual(created.staff_member_id, employee.id)

    def test_staff_account_requires_staff_member_link(self):
        self.login_as(self.admin)
        resp = self.client.post('/api/users/', {
            'account': 'newstaff02', 'password': 'newpass123', 'displayName': 'x', 'role': 'staff',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_one_employee_cannot_get_two_login_accounts(self):
        self.login_as(self.admin)
        resp = self.client.post('/api/users/', {
            'account': 'second-account-same-employee', 'password': 'newpass123', 'displayName': 'x',
            'role': 'staff', 'staffMemberId': self.staff_employee.id,
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_branch_role_cannot_create_staff_accounts(self):
        employee = StaffMember.objects.create(name='新员工', branch=self.branch_a)
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/users/', {
            'account': 'newstaff03', 'password': 'newpass123', 'displayName': 'x',
            'role': 'staff', 'staffMemberId': employee.id,
        }, format='json')
        self.assertEqual(resp.status_code, 403)


class StaffRolePermissionBoundaryTests(ApiTestCase):
    """The staff role must reach only its explicit self-service allowlist —
    everything else is blocked project-wide by DenyStaffRole, not by the
    frontend hiding menu items."""

    BLOCKED_GET_ENDPOINTS = [
        '/api/staff/', '/api/payment-methods/', '/api/daily-reports/', '/api/purchases/',
        '/api/suppliers/', '/api/branches/', '/api/users/', '/api/dashboard/summary/',
        '/api/wage-rules/',
    ]

    def test_staff_blocked_from_everything_outside_the_allowlist(self):
        self.login_as(self.staff_user)
        for endpoint in self.BLOCKED_GET_ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                resp = self.client.get(endpoint)
                self.assertEqual(resp.status_code, 403, f'{endpoint} should be 403 for staff, got {resp.status_code}')

    def test_staff_can_reach_me_change_password_and_preference(self):
        self.login_as(self.staff_user)
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 200)
        self.assertEqual(self.client.get('/api/auth/preference/').status_code, 200)
        resp = self.client.post('/api/auth/change-password/', {
            'old_password': TEST_PASSWORD, 'new_password': 'newpass456',
        })
        self.assertEqual(resp.status_code, 200)

    def test_admin_and_branch_are_unaffected_by_the_staff_block(self):
        self.login_as(self.admin)
        self.assertEqual(self.client.get('/api/staff/').status_code, 200)
        self.login_as(self.branch_a_user)
        self.assertEqual(self.client.get('/api/staff/').status_code, 200)
