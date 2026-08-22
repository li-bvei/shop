from common.test_utils import ApiTestCase

from .models import Branch
from paymentmethods.models import PaymentMethodDef


class BranchDeletionTests(ApiTestCase):
    def test_cannot_delete_branch_with_accounts(self):
        self.login_as(self.admin)
        resp = self.client.delete(f'/api/branches/{self.branch_a.id}/')
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(Branch.objects.filter(id=self.branch_a.id).exists())

    def test_can_delete_branch_with_no_accounts(self):
        empty_branch = Branch.objects.create(
            id='empty-branch', organization=self.org, code='empty-branch', name_zh='空分店', name_ja='空の支店',
        )
        self.login_as(self.admin)
        resp = self.client.delete(f'/api/branches/{empty_branch.id}/')
        self.assertEqual(resp.status_code, 204)


class BranchCreationSeedsPaymentMethodsTests(ApiTestCase):
    def test_new_branch_gets_default_payment_methods(self):
        self.login_as(self.admin)
        resp = self.client.post('/api/branches/', {
            'id': 'new-branch', 'name_zh': '新分店', 'name_ja': '新支店',
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        methods = PaymentMethodDef.objects.filter(branch_id='new-branch')
        self.assertEqual(methods.count(), 8)
        self.assertTrue(methods.filter(protected=True).exists())


class BranchPermissionBoundaryTests(ApiTestCase):
    """A branch account must never be able to create, edit, or delete a
    branch — including its own — regardless of what the frontend hides;
    and it must only ever be able to read its own branch, not any other."""

    def test_branch_account_can_only_list_its_own_branch(self):
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/branches/')
        self.assertEqual(resp.status_code, 200)
        ids = [row['id'] for row in resp.data]
        self.assertEqual(ids, [self.branch_a.id])

    def test_branch_account_cannot_read_another_branch_by_id(self):
        self.login_as(self.branch_a_user)
        resp = self.client.get(f'/api/branches/{self.branch_b.id}/')
        self.assertEqual(resp.status_code, 404)

    def test_branch_account_cannot_create_branch(self):
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/branches/', {
            'id': 'forged-branch', 'name_zh': '伪造分店', 'name_ja': '偽の支店',
        }, format='json')
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Branch.objects.filter(id='forged-branch').exists())

    def test_branch_account_cannot_update_its_own_branch(self):
        self.login_as(self.branch_a_user)
        resp = self.client.patch(f'/api/branches/{self.branch_a.id}/', {'name_zh': '改名'}, format='json')
        self.assertEqual(resp.status_code, 403)
        self.branch_a.refresh_from_db()
        self.assertNotEqual(self.branch_a.name_zh, '改名')

    def test_branch_account_cannot_delete_a_branch(self):
        self.login_as(self.branch_a_user)
        resp = self.client.delete(f'/api/branches/{self.branch_a.id}/')
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Branch.objects.filter(id=self.branch_a.id).exists())

    def test_staff_account_blocked_entirely(self):
        self.login_as(self.staff_user)
        resp = self.client.get('/api/branches/')
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_still_manage_branches(self):
        self.login_as(self.admin)
        resp = self.client.get('/api/branches/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), Branch.objects.count())
        resp = self.client.patch(f'/api/branches/{self.branch_a.id}/', {'name_zh': '心斋桥新名'}, format='json')
        self.assertEqual(resp.status_code, 200)
