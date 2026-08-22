from common.test_utils import ApiTestCase

from .models import PaymentMethodDef


class BranchScopingTests(ApiTestCase):
    """Regression coverage for the branch-isolation bug fixed this round:
    PaymentMethodDefViewSet previously had no scoping at all, so any
    authenticated branch account could read/write every branch's rows."""

    def test_branch_account_only_sees_own_branch(self):
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/payment-methods/')
        self.assertEqual(resp.status_code, 200)
        branches = {row['branch'] for row in resp.data}
        self.assertEqual(branches, {self.branch_a.id})

    def test_branch_account_cannot_read_another_branch_by_filter(self):
        self.login_as(self.branch_a_user)
        resp = self.client.get(f'/api/payment-methods/?branch={self.branch_b.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, [])

    def test_branch_account_cannot_retrieve_another_branchs_row_by_id(self):
        other_row = PaymentMethodDef.objects.filter(branch=self.branch_b, protected=False).first()
        self.login_as(self.branch_a_user)
        resp = self.client.get(f'/api/payment-methods/{other_row.id}/')
        self.assertEqual(resp.status_code, 404)

    def test_create_with_other_branch_is_forced_to_own_branch(self):
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/payment-methods/', {
            'branch': self.branch_b.id, 'code': 'attack', 'custom_name': 'x',
            'i18n_key': '', 'sort_order': 99,
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['branch'], self.branch_a.id)

    def test_update_cannot_reassign_branch(self):
        # A fresh, branch-a-only code — reassigning branch_a's *default*
        # rows (e.g. code='creditCard') to branch_b would collide with
        # branch_b's own identically-coded default row and 400 on the
        # (branch, code) uniqueness constraint regardless of whether the
        # branch-immutability fix works, which would make this test pass
        # for the wrong reason.
        own_row = PaymentMethodDef.objects.create(
            branch=self.branch_a, code='custom-test-code', custom_name='原名', sort_order=99,
        )
        self.login_as(self.branch_a_user)
        resp = self.client.patch(f'/api/payment-methods/{own_row.id}/', {
            'branch': self.branch_b.id, 'custom_name': 'renamed',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['branch'], self.branch_a.id)
        self.assertEqual(resp.data['custom_name'], 'renamed')

    def test_admin_sees_every_branch(self):
        self.login_as(self.admin)
        resp = self.client.get('/api/payment-methods/')
        branches = {row['branch'] for row in resp.data}
        self.assertEqual(branches, {self.branch_a.id, self.branch_b.id})

    def test_admin_can_scope_via_filter(self):
        self.login_as(self.admin)
        resp = self.client.get(f'/api/payment-methods/?branch={self.branch_b.id}')
        branches = {row['branch'] for row in resp.data}
        self.assertEqual(branches, {self.branch_b.id})


class ProtectedCashTests(ApiTestCase):
    def test_protected_row_cannot_be_renamed(self):
        cash = PaymentMethodDef.objects.get(branch=self.branch_a, protected=True)
        self.login_as(self.branch_a_user)
        resp = self.client.patch(f'/api/payment-methods/{cash.id}/', {'custom_name': 'x'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_protected_row_cannot_be_deleted(self):
        cash = PaymentMethodDef.objects.get(branch=self.branch_a, protected=True)
        self.login_as(self.branch_a_user)
        resp = self.client.delete(f'/api/payment-methods/{cash.id}/')
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(PaymentMethodDef.objects.filter(id=cash.id).exists())

    def test_non_protected_row_can_be_deleted(self):
        row = PaymentMethodDef.objects.filter(branch=self.branch_a, protected=False).first()
        self.login_as(self.branch_a_user)
        resp = self.client.delete(f'/api/payment-methods/{row.id}/')
        self.assertEqual(resp.status_code, 204)

    def test_protected_row_sort_order_can_be_changed(self):
        cash = PaymentMethodDef.objects.get(branch=self.branch_a, protected=True)
        self.login_as(self.branch_a_user)
        resp = self.client.patch(f'/api/payment-methods/{cash.id}/', {'sort_order': 5}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['sort_order'], 5)
        self.assertEqual(resp.data['custom_name'], cash.custom_name)


class ReorderTests(ApiTestCase):
    def test_reorder_persists_new_order(self):
        rows = list(PaymentMethodDef.objects.filter(branch=self.branch_a).order_by('sort_order'))
        reversed_ids = [r.id for r in reversed(rows)]
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/payment-methods/reorder/', {
            'branch': self.branch_a.id, 'order': reversed_ids,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([r['id'] for r in resp.data], reversed_ids)
        for index, pk in enumerate(reversed_ids):
            self.assertEqual(PaymentMethodDef.objects.get(id=pk).sort_order, index)

    def test_reorder_can_move_protected_cash_row(self):
        rows = list(PaymentMethodDef.objects.filter(branch=self.branch_a).order_by('sort_order'))
        cash = next(r for r in rows if r.protected)
        others = [r for r in rows if not r.protected]
        new_order = [r.id for r in others] + [cash.id]
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/payment-methods/reorder/', {
            'branch': self.branch_a.id, 'order': new_order,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        cash.refresh_from_db()
        self.assertEqual(cash.sort_order, len(new_order) - 1)
        # still undeletable/unrenamable — reorder only ever touches sort_order
        resp = self.client.patch(f'/api/payment-methods/{cash.id}/', {'custom_name': 'x'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_reorder_rejects_partial_list(self):
        rows = list(PaymentMethodDef.objects.filter(branch=self.branch_a).order_by('sort_order'))
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/payment-methods/reorder/', {
            'branch': self.branch_a.id, 'order': [rows[0].id],
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_reorder_rejects_ids_from_another_branch(self):
        branch_b_row = PaymentMethodDef.objects.filter(branch=self.branch_b).first()
        own_rows = list(PaymentMethodDef.objects.filter(branch=self.branch_a).order_by('sort_order'))
        order = [r.id for r in own_rows[1:]] + [branch_b_row.id]
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/payment-methods/reorder/', {
            'branch': self.branch_a.id, 'order': order,
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        # nothing was reordered
        for row in own_rows:
            row.refresh_from_db()
        self.assertEqual([r.sort_order for r in own_rows], sorted(r.sort_order for r in own_rows))

    def test_reorder_rejects_another_branchs_id_even_disguised_as_own_branch(self):
        # branch_a_user tries to reorder branch_a's list but sneaks in a
        # branch_b id — BranchScopedQuerysetMixin excludes it from qs, so
        # it never matches the "exactly the existing ids" check.
        branch_b_row = PaymentMethodDef.objects.filter(branch=self.branch_b).first()
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/payment-methods/reorder/', {
            'branch': self.branch_a.id, 'order': [branch_b_row.id],
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        branch_b_row.refresh_from_db()

    def test_admin_can_reorder_any_branch_in_org(self):
        rows = list(PaymentMethodDef.objects.filter(branch=self.branch_b).order_by('sort_order'))
        reversed_ids = [r.id for r in reversed(rows)]
        self.login_as(self.admin)
        resp = self.client.post('/api/payment-methods/reorder/', {
            'branch': self.branch_b.id, 'order': reversed_ids,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
