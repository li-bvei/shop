from common.test_utils import ApiTestCase

from .models import PurchaseRecord, Supplier
from .utils import normalize_item_name


class AmountCalculationTests(ApiTestCase):
    def test_amount_is_server_computed_not_client_supplied(self):
        supplier = Supplier.objects.create(organization=self.org, name='测试供应商')
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/purchases/', {
            'date': '2026-01-01', 'supplier': supplier.id, 'item_name': '测试项目',
            'quantity': 3, 'unit_price': 150, 'amount': 999999,  # attacker-supplied, must be ignored
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(float(resp.data['amount']), 450.0)

    def test_amount_recomputed_on_update(self):
        supplier = Supplier.objects.create(organization=self.org, name='测试供应商')
        record = PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-01-01', supplier=supplier,
            item_name='x', quantity=2, unit_price=100,
        )
        self.assertEqual(float(record.amount), 200.0)
        self.login_as(self.branch_a_user)
        resp = self.client.patch(f'/api/purchases/{record.id}/', {'quantity': 5}, format='json')
        self.assertEqual(float(resp.data['amount']), 500.0)


class BranchScopingTests(ApiTestCase):
    def test_branch_account_cannot_see_other_branch_purchases(self):
        supplier = Supplier.objects.create(organization=self.org, name='测试供应商')
        PurchaseRecord.objects.create(
            branch=self.branch_b, date='2026-01-01', supplier=supplier,
            item_name='x', quantity=1, unit_price=100,
        )
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/purchases/')
        self.assertEqual(resp.data['results'], [])

    def test_branch_account_create_forces_own_branch(self):
        supplier = Supplier.objects.create(organization=self.org, name='测试供应商')
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/purchases/', {
            'branch': self.branch_b.id, 'date': '2026-01-01', 'supplier': supplier.id,
            'item_name': 'x', 'quantity': 1, 'unit_price': 100,
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['branch'], self.branch_a.id)

    def test_admin_sees_all_branches(self):
        supplier = Supplier.objects.create(organization=self.org, name='测试供应商')
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-01-01', supplier=supplier, item_name='a', quantity=1, unit_price=1,
        )
        PurchaseRecord.objects.create(
            branch=self.branch_b, date='2026-01-01', supplier=supplier, item_name='b', quantity=1, unit_price=1,
        )
        self.login_as(self.admin)
        resp = self.client.get('/api/purchases/')
        self.assertEqual(resp.data['count'], 2)


class ItemNameNormalizationTests(ApiTestCase):
    def test_normalize_collapses_width_and_whitespace_variants(self):
        self.assertEqual(
            normalize_item_name('レタス　1個　（青木青果）'),
            normalize_item_name('レタス 1個 (青木青果)'),
        )

    def test_normalize_never_merges_different_quantity_units(self):
        # '1個' (per head) and '1ケース' (per case) are different SKUs —
        # normalization must not collapse them into the same key.
        self.assertNotEqual(
            normalize_item_name('レタス 1個（青木青果）'),
            normalize_item_name('レタス 1ケース（青木青果）'),
        )

    def test_normalized_field_is_set_on_save(self):
        supplier = Supplier.objects.create(organization=self.org, name='测试供应商')
        record = PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-01-01', supplier=supplier,
            item_name='レタス　1個　（青木青果）', quantity=1, unit_price=100,
        )
        self.assertEqual(record.item_name_normalized, 'レタス 1個 (青木青果)')


class ListFilteringAndPaginationTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.supplier = Supplier.objects.create(organization=self.org, name='供应商A')
        self.other_supplier = Supplier.objects.create(organization=self.org, name='供应商B')

    def test_month_filter(self):
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-01-15', supplier=self.supplier,
            item_name='一月货', quantity=1, unit_price=100,
        )
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-02-15', supplier=self.supplier,
            item_name='二月货', quantity=1, unit_price=100,
        )
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/purchases/?month=2026-01')
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['item_name'], '一月货')

    def test_date_range_filter(self):
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-01-05', supplier=self.supplier,
            item_name='早', quantity=1, unit_price=100,
        )
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-01-25', supplier=self.supplier,
            item_name='晚', quantity=1, unit_price=100,
        )
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/purchases/?date_from=2026-01-01&date_to=2026-01-10')
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['item_name'], '早')

    def test_item_name_filter_matches_normalized_form(self):
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-01-05', supplier=self.supplier,
            item_name='レタス　1個（青木青果）', quantity=1, unit_price=100,
        )
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/purchases/?item_name=レタス 1個(青木青果)')
        self.assertEqual(resp.data['count'], 1)

    def test_pagination_page_size(self):
        for i in range(60):
            PurchaseRecord.objects.create(
                branch=self.branch_a, date='2026-01-01', supplier=self.supplier,
                item_name=f'item{i}', quantity=1, unit_price=100,
            )
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/purchases/')
        self.assertEqual(resp.data['count'], 60)
        self.assertEqual(len(resp.data['results']), 50)
        self.assertIsNotNone(resp.data['next'])

    def test_ordering_by_unit_price(self):
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-01-01', supplier=self.supplier,
            item_name='贵', quantity=1, unit_price=500,
        )
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-01-01', supplier=self.supplier,
            item_name='便宜', quantity=1, unit_price=50,
        )
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/purchases/?ordering=unit_price')
        prices = [float(r['unit_price']) for r in resp.data['results']]
        self.assertEqual(prices, sorted(prices))

    def test_supplier_never_mixed_in_month_filter(self):
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-01-01', supplier=self.supplier,
            item_name='同名商品', quantity=1, unit_price=100,
        )
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-01-01', supplier=self.other_supplier,
            item_name='同名商品', quantity=1, unit_price=200,
        )
        self.login_as(self.branch_a_user)
        resp = self.client.get(f'/api/purchases/?supplier={self.supplier.id}')
        self.assertEqual(resp.data['count'], 1)


class PriceComparisonTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.supplier = Supplier.objects.create(organization=self.org, name='供应商A')

    def test_price_rise_flagged_against_prior_month(self):
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-01-10', supplier=self.supplier,
            item_name='胡萝卜', quantity=1, unit_price=100,
        )
        risen = PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-02-10', supplier=self.supplier,
            item_name='胡萝卜', quantity=1, unit_price=150,
        )
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/purchases/?month=2026-02')
        row = next(r for r in resp.data['results'] if r['id'] == risen.id)
        self.assertEqual(row['price_direction'], 'up')
        self.assertEqual(float(row['prior_month_avg_unit_price']), 100.0)
        self.assertEqual(float(row['price_delta_amount']), 50.0)
        self.assertEqual(float(row['price_delta_percent']), 50.0)

    def test_no_flag_when_no_prior_month_data(self):
        # Only a same-year-earlier record exists (not the immediately
        # preceding calendar month) — must never be used as the baseline.
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-01-10', supplier=self.supplier,
            item_name='萝卜', quantity=1, unit_price=100,
        )
        record = PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-03-10', supplier=self.supplier,
            item_name='萝卜', quantity=1, unit_price=999,
        )
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/purchases/?month=2026-03')
        row = next(r for r in resp.data['results'] if r['id'] == record.id)
        self.assertIsNone(row['price_direction'])
        self.assertIsNone(row['price_delta_amount'])
        self.assertIsNone(row['price_delta_percent'])

    def test_acceptance_example_delta_100_and_10_percent(self):
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-07-10', supplier=self.supplier,
            item_name='验收商品', quantity=1, unit_price=1000,
        )
        current = PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-08-10', supplier=self.supplier,
            item_name='验收商品', quantity=1, unit_price=1100,
        )
        self.login_as(self.branch_a_user)
        row = next(r for r in self.client.get('/api/purchases/?month=2026-08').data['results'] if r['id'] == current.id)
        self.assertEqual(float(row['price_delta_amount']), 100)
        self.assertEqual(float(row['price_delta_percent']), 10.0)

    def test_suggestions_query_count_does_not_grow_per_item(self):
        for index in range(40):
            PurchaseRecord.objects.create(
                branch=self.branch_a, date='2026-08-10', supplier=self.supplier,
                item_name=f'商品{index}', quantity=1, unit_price=100 + index,
            )
        self.login_as(self.branch_a_user)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(f'/api/purchases/suggestions/?supplier={self.supplier.id}')
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(captured), 8)

    def test_price_comparison_never_mixes_suppliers(self):
        other_supplier = Supplier.objects.create(organization=self.org, name='供应商B')
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-01-10', supplier=other_supplier,
            item_name='葱', quantity=1, unit_price=999,
        )
        record = PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-02-10', supplier=self.supplier,
            item_name='葱', quantity=1, unit_price=100,
        )
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/purchases/?month=2026-02')
        row = next(r for r in resp.data['results'] if r['id'] == record.id)
        self.assertIsNone(row['price_direction'])

    def test_price_change_filter_requires_month(self):
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/purchases/?price_change=up')
        self.assertEqual(resp.status_code, 400)

    def test_price_change_filter_returns_only_matching_direction(self):
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-01-10', supplier=self.supplier,
            item_name='上涨品', quantity=1, unit_price=100,
        )
        risen = PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-02-10', supplier=self.supplier,
            item_name='上涨品', quantity=1, unit_price=150,
        )
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-01-10', supplier=self.supplier,
            item_name='下跌品', quantity=1, unit_price=100,
        )
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-02-10', supplier=self.supplier,
            item_name='下跌品', quantity=1, unit_price=50,
        )
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/purchases/?month=2026-02&price_change=up')
        ids = [r['id'] for r in resp.data['results']]
        self.assertEqual(ids, [risen.id])

    def test_price_history_scoped_to_branch_supplier_item(self):
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-01-10', supplier=self.supplier,
            item_name='大蒜', quantity=1, unit_price=100,
        )
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-02-10', supplier=self.supplier,
            item_name='大蒜', quantity=1, unit_price=120,
        )
        # different branch — must not appear
        PurchaseRecord.objects.create(
            branch=self.branch_b, date='2026-02-10', supplier=self.supplier,
            item_name='大蒜', quantity=1, unit_price=999,
        )
        self.login_as(self.admin)
        resp = self.client.get(
            f'/api/purchases/price_history/?branch={self.branch_a.id}'
            f'&supplier={self.supplier.id}&item_name=大蒜',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 2)
        self.assertTrue(all(float(r['unitPrice']) != 999 for r in resp.data))

    def test_supplier_comparison_mixes_suppliers_by_design(self):
        other_supplier = Supplier.objects.create(organization=self.org, name='供应商B')
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-01-10', supplier=self.supplier,
            item_name='鸡蛋', quantity=1, unit_price=200,
        )
        PurchaseRecord.objects.create(
            branch=self.branch_a, date='2026-01-10', supplier=other_supplier,
            item_name='鸡蛋', quantity=1, unit_price=180,
        )
        self.login_as(self.admin)
        resp = self.client.get(f'/api/purchases/supplier_comparison/?branch={self.branch_a.id}&item_name=鸡蛋')
        self.assertEqual(resp.status_code, 200)
        supplier_ids = {r['supplierId'] for r in resp.data}
        self.assertEqual(supplier_ids, {self.supplier.id, other_supplier.id})
        # cheapest first
        self.assertEqual(resp.data[0]['supplierId'], other_supplier.id)
