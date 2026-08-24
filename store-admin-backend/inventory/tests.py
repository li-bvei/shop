from decimal import Decimal

from rest_framework.exceptions import ValidationError

from common.test_utils import ApiTestCase, TwoOrganizationApiTestCase

from .models import Product, Stock, StockTransaction
from .services import adjust_stock


class AdjustStockServiceTests(ApiTestCase):
    def test_purchase_in_creates_stock_and_ledger_entry(self):
        product = Product.objects.create(organization=self.org, name='测试商品')
        stock, record = adjust_stock(
            branch=self.branch_a, product=product,
            transaction_type=StockTransaction.TransactionType.PURCHASE_IN, quantity=Decimal('10'),
        )
        self.assertEqual(stock.quantity, Decimal('10'))
        self.assertEqual(record.transaction_type, StockTransaction.TransactionType.PURCHASE_IN)
        self.assertEqual(StockTransaction.objects.count(), 1)

    def test_sale_out_decrements_existing_stock(self):
        product = Product.objects.create(organization=self.org, name='测试商品')
        adjust_stock(
            branch=self.branch_a, product=product,
            transaction_type=StockTransaction.TransactionType.PURCHASE_IN, quantity=Decimal('10'),
        )
        stock, _ = adjust_stock(
            branch=self.branch_a, product=product,
            transaction_type=StockTransaction.TransactionType.SALE_OUT, quantity=Decimal('4'),
        )
        self.assertEqual(stock.quantity, Decimal('6'))

    def test_sale_out_cannot_drive_stock_negative(self):
        product = Product.objects.create(organization=self.org, name='测试商品')
        adjust_stock(
            branch=self.branch_a, product=product,
            transaction_type=StockTransaction.TransactionType.PURCHASE_IN, quantity=Decimal('3'),
        )
        with self.assertRaises(ValidationError):
            adjust_stock(
                branch=self.branch_a, product=product,
                transaction_type=StockTransaction.TransactionType.SALE_OUT, quantity=Decimal('4'),
            )
        # The failed attempt must not have partially applied.
        stock = Stock.objects.get(branch=self.branch_a, product=product)
        self.assertEqual(stock.quantity, Decimal('3'))
        self.assertEqual(StockTransaction.objects.count(), 1)

    def test_zero_or_negative_quantity_rejected(self):
        product = Product.objects.create(organization=self.org, name='测试商品')
        with self.assertRaises(ValidationError):
            adjust_stock(
                branch=self.branch_a, product=product,
                transaction_type=StockTransaction.TransactionType.PURCHASE_IN, quantity=Decimal('0'),
            )

    def test_stock_is_scoped_per_branch(self):
        product = Product.objects.create(organization=self.org, name='测试商品')
        adjust_stock(
            branch=self.branch_a, product=product,
            transaction_type=StockTransaction.TransactionType.PURCHASE_IN, quantity=Decimal('5'),
        )
        self.assertFalse(Stock.objects.filter(branch=self.branch_b, product=product).exists())


class StockApiTests(ApiTestCase):
    def test_branch_account_can_only_adjust_own_branch(self):
        product = Product.objects.create(organization=self.org, name='测试商品')
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/stock/adjust/', {
            'branch': self.branch_b.id, 'product': product.id,
            'transaction_type': 'purchase_in', 'quantity': 5,
        }, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_branch_account_adjust_defaults_to_own_branch(self):
        product = Product.objects.create(organization=self.org, name='测试商品')
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/stock/adjust/', {
            'product': product.id, 'transaction_type': 'purchase_in', 'quantity': 5,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data['branch'], self.branch_a.id)
        self.assertEqual(float(resp.data['quantity']), 5.0)

    def test_low_stock_filter(self):
        low = Product.objects.create(organization=self.org, name='低库存商品', low_stock_threshold=5)
        high = Product.objects.create(organization=self.org, name='充足商品', low_stock_threshold=5)
        adjust_stock(branch=self.branch_a, product=low, transaction_type='purchase_in', quantity=Decimal('2'))
        adjust_stock(branch=self.branch_a, product=high, transaction_type='purchase_in', quantity=Decimal('50'))
        self.login_as(self.admin)
        resp = self.client.get('/api/stock/?low_stock=true')
        names = [row['product_name'] for row in resp.data]
        self.assertIn('低库存商品', names)
        self.assertNotIn('充足商品', names)

    def test_insufficient_stock_returns_400(self):
        product = Product.objects.create(organization=self.org, name='测试商品')
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/stock/adjust/', {
            'product': product.id, 'transaction_type': 'sale_out', 'quantity': 1,
        }, format='json')
        self.assertEqual(resp.status_code, 400)


class ProductApiTests(ApiTestCase):
    def test_jan_code_lookup(self):
        Product.objects.create(organization=self.org, name='可乐', jan_code='4901234567894')
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/products/lookup/?jan=4901234567894')
        self.assertEqual(resp.data['name'], '可乐')

    def test_jan_code_lookup_miss_returns_null(self):
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/products/lookup/?jan=0000000000000')
        self.assertIsNone(resp.data)

    def test_duplicate_jan_code_within_org_rejected(self):
        Product.objects.create(organization=self.org, name='可乐', jan_code='4901234567894')
        self.login_as(self.admin)
        resp = self.client.post('/api/products/', {
            'name': '可乐2', 'jan_code': '4901234567894',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_blank_jan_code_can_repeat(self):
        Product.objects.create(organization=self.org, name='散装蔬菜A', jan_code='')
        self.login_as(self.admin)
        resp = self.client.post('/api/products/', {'name': '散装蔬菜B', 'jan_code': ''}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)


class CrossOrganizationIsolationTests(TwoOrganizationApiTestCase):
    def test_product_lookup_scoped_to_own_organization(self):
        Product.objects.create(organization=self.org_a, name='A集团商品', jan_code='1111111111111')
        self.login_as(self.branch_b1_user)
        resp = self.client.get('/api/products/lookup/?jan=1111111111111')
        self.assertIsNone(resp.data)

    def test_stock_adjust_cannot_target_other_organization_branch(self):
        product = Product.objects.create(organization=self.org_b, name='B集团商品')
        self.login_as(self.admin_a)
        resp = self.client.post('/api/stock/adjust/', {
            'branch': self.branch_b1.id, 'product': product.id,
            'transaction_type': 'purchase_in', 'quantity': 3,
        }, format='json')
        self.assertEqual(resp.status_code, 403)
