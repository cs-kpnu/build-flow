"""
Tests for model methods:
  - Material.total_stock property
  - Material.update_material_avg_price()
"""
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User

from warehouse.models import Material, Warehouse, Transaction
from warehouse.services import inventory
from warehouse.tests.base import BaseTestCase


class MaterialTotalStockTests(BaseTestCase):
    """Tests for Material.total_stock property."""

    def test_zero_with_no_transactions(self):
        self.assertEqual(self.mat_cement.total_stock, Decimal('0.000'))

    def test_after_incoming(self):
        self.add_stock(qty=100)
        self.mat_cement.refresh_from_db()
        self.assertEqual(self.mat_cement.total_stock, Decimal('100.000'))

    def test_after_writeoff(self):
        self.add_stock(qty=100)
        inventory.create_writeoff(
            self.mat_cement, self.wh_main, 30, self.staff_user, transaction_type='OUT'
        )
        self.assertEqual(self.mat_cement.total_stock, Decimal('70.000'))

    def test_loss_counts_as_out(self):
        self.add_stock(qty=100)
        inventory.create_writeoff(
            self.mat_cement, self.wh_main, 10, self.staff_user, transaction_type='LOSS'
        )
        self.assertEqual(self.mat_cement.total_stock, Decimal('90.000'))

    def test_across_all_warehouses(self):
        """total_stock sums IN across ALL warehouses."""
        self.add_stock(qty=50, warehouse=self.wh_main)
        self.add_stock(qty=30, warehouse=self.wh_site)
        # total = 80 across both warehouses
        self.assertEqual(self.mat_cement.total_stock, Decimal('80.000'))

    def test_transfer_net_zero(self):
        """Transfer OUT+IN is net-zero for total_stock across all warehouses."""
        self.add_stock(qty=100, warehouse=self.wh_main)
        # Transfer 40 units from main to site
        inventory.create_transfer(
            self.staff_user, self.mat_cement, self.wh_main, self.wh_site, 40
        )
        # total_stock: IN=100+40=140, OUT=40 → net = 100
        self.assertEqual(self.mat_cement.total_stock, Decimal('100.000'))

    def test_decimal_precision(self):
        """total_stock is quantized to 3 decimal places."""
        self.add_stock(qty=Decimal('10.123'))
        result = self.mat_cement.total_stock
        # Check it has exactly 3 decimal places
        self.assertEqual(result, result.quantize(Decimal('0.001')))


class MaterialAvgPriceTests(BaseTestCase):
    """Tests for Material.update_material_avg_price()."""

    def test_single_incoming_sets_price(self):
        self.add_stock(qty=100, price=Decimal('40.00'))
        self.mat_cement.refresh_from_db()
        self.assertEqual(self.mat_cement.current_avg_price, Decimal('40.00'))

    def test_weighted_average(self):
        """Two equal-qty receipts at different prices → midpoint avg."""
        self.add_stock(qty=100, price=Decimal('40.00'))
        self.add_stock(qty=100, price=Decimal('60.00'))
        self.mat_cement.refresh_from_db()
        self.assertEqual(self.mat_cement.current_avg_price, Decimal('50.00'))

    def test_weighted_average_unequal_quantities(self):
        """(200*30 + 100*60) / 300 = (6000+6000)/300 = 40.00"""
        self.add_stock(qty=200, price=Decimal('30.00'))
        self.add_stock(qty=100, price=Decimal('60.00'))
        self.mat_cement.refresh_from_db()
        expected = ((200 * 30 + 100 * 60) / 300)
        self.assertEqual(self.mat_cement.current_avg_price, Decimal('40.00'))

    def test_no_transactions_no_crash(self):
        """Calling on material with no transactions should not raise."""
        mat = Material.objects.create(
            name='NoTxMat', unit='pcs', current_avg_price=Decimal('5.00')
        )
        try:
            mat.update_material_avg_price()
        except Exception as e:
            self.fail(f"update_material_avg_price raised unexpectedly: {e}")

    def test_ignores_out_transactions(self):
        """OUT transactions do not factor into avg price calc."""
        self.add_stock(qty=100, price=Decimal('50.00'))
        inventory.create_writeoff(
            self.mat_cement, self.wh_main, 10, self.staff_user, transaction_type='OUT'
        )
        self.mat_cement.refresh_from_db()
        # Price should still be based only on IN transactions
        self.assertEqual(self.mat_cement.current_avg_price, Decimal('50.00'))

    def test_price_zero_when_incoming_has_zero_price(self):
        """Incoming with price=0 should leave avg price as 0 (no update triggered)."""
        original_price = self.mat_cement.current_avg_price
        # price=None defaults to 0.00 → update_material_avg_price NOT called
        self.add_stock(qty=100, price=None)
        self.mat_cement.refresh_from_db()
        self.assertEqual(self.mat_cement.current_avg_price, original_price)
