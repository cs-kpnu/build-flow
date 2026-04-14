"""
Tests for views/transactions.py:
  - warehouse_detail
  - transaction_detail
  - add_transaction
  - add_transfer
"""
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse

from warehouse.models import Transaction
from warehouse.services import inventory
from warehouse.tests.base import BaseTestCase


class WarehouseDetailViewTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.add_stock(qty=50)

    def test_allowed_foreman_gets_200(self):
        self.login_foreman()
        resp = self.client.get(reverse('warehouse_detail', args=[self.wh_main.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_forbidden_user_gets_404(self):
        """other_user has no warehouse access → 404."""
        self.client.force_login(self.other_user)
        resp = self.client.get(reverse('warehouse_detail', args=[self.wh_main.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_staff_can_access_any_warehouse(self):
        self.login_staff()
        resp = self.client.get(reverse('warehouse_detail', args=[self.wh_other.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_filter_by_type_in(self):
        self.login_foreman()
        resp = self.client.get(
            reverse('warehouse_detail', args=[self.wh_main.pk]),
            {'type': 'IN'}
        )
        self.assertEqual(resp.status_code, 200)

    def test_filter_by_material(self):
        self.login_foreman()
        resp = self.client.get(
            reverse('warehouse_detail', args=[self.wh_main.pk]),
            {'material': self.mat_cement.pk}
        )
        self.assertEqual(resp.status_code, 200)

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('warehouse_detail', args=[self.wh_main.pk]))
        self.assertEqual(resp.status_code, 302)


class TransactionDetailViewTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.tx = self.add_stock(qty=10)

    def test_allowed_user_sees_transaction(self):
        self.login_foreman()
        resp = self.client.get(reverse('transaction_detail', args=[self.tx.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_forbidden_user_gets_404(self):
        """Transaction is on wh_main; other_user has no access."""
        self.client.force_login(self.other_user)
        resp = self.client.get(reverse('transaction_detail', args=[self.tx.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_staff_can_see_any_transaction(self):
        self.login_staff()
        resp = self.client.get(reverse('transaction_detail', args=[self.tx.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('transaction_detail', args=[self.tx.pk]))
        self.assertEqual(resp.status_code, 302)


class AddTransactionViewTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.add_stock(qty=100)

    def _post_data(self, t_type='IN', qty='10.000', wh=None, mat=None):
        return {
            'transaction_type': t_type,
            'warehouse': (wh or self.wh_main).pk,
            'material': (mat or self.mat_cement).pk,
            'quantity': qty,
            'description': 'test',
        }

    def test_get_renders_form(self):
        self.login_foreman()
        resp = self.client.get(reverse('add_transaction'))
        self.assertEqual(resp.status_code, 200)

    def test_post_in_creates_transaction_and_redirects(self):
        self.login_foreman()
        initial_count = Transaction.objects.count()
        resp = self.client.post(reverse('add_transaction'), self._post_data('IN'))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Transaction.objects.count(), initial_count + 1)

    def test_post_out_within_stock_creates_transaction(self):
        self.login_foreman()
        resp = self.client.post(reverse('add_transaction'), self._post_data('OUT', qty='20.000'))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Transaction.objects.filter(transaction_type='OUT').exists())

    def test_post_out_exceeds_stock_shows_error(self):
        """Insufficient stock → re-renders form (200), no redirect, no OUT transaction."""
        self.login_foreman()
        resp = self.client.post(reverse('add_transaction'), self._post_data('OUT', qty='9999.000'))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Transaction.objects.filter(transaction_type='OUT').exists())

    def test_post_loss_creates_loss_transaction(self):
        self.login_foreman()
        resp = self.client.post(reverse('add_transaction'), self._post_data('LOSS', qty='5.000'))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Transaction.objects.filter(transaction_type='LOSS').exists())

    def test_forbidden_warehouse_gets_404(self):
        """other_user has no warehouse access."""
        self.client.force_login(self.other_user)
        resp = self.client.post(reverse('add_transaction'), self._post_data(wh=self.wh_main))
        self.assertEqual(resp.status_code, 404)

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('add_transaction'))
        self.assertEqual(resp.status_code, 302)


class AddTransferViewTests(BaseTestCase):
    """
    add_transfer tests.
    IMPORTANT: foreman_user needs access to BOTH source and target warehouses,
    otherwise TransferForm fails with "Select a valid choice" before reaching
    the business logic checks.
    """

    def setUp(self):
        super().setUp()
        # Give foreman access to wh_site as well (for the transfer target)
        self.foreman_user.profile.warehouses.add(self.wh_site)
        self.add_stock(qty=100)

    def tearDown(self):
        # Clean up the M2M addition (not strictly necessary as TestCase rolls back,
        # but be explicit about test isolation)
        self.foreman_user.profile.warehouses.remove(self.wh_site)
        super().tearDown()

    def _post_transfer(self, qty='20.000', source=None, target=None):
        from django.utils import timezone
        return {
            'source_warehouse': (source or self.wh_main).pk,
            'target_warehouse': (target or self.wh_site).pk,
            'material': self.mat_cement.pk,
            'quantity': qty,
            'date': timezone.now().date().isoformat(),
            'description': 'test transfer',
        }

    def test_get_renders_form_with_stock_json(self):
        self.login_foreman()
        resp = self.client.get(reverse('add_transfer'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('stock_json', resp.context)

    def test_post_valid_transfer_redirects_to_journal(self):
        self.login_foreman()
        resp = self.client.post(reverse('add_transfer'), self._post_transfer())
        self.assertRedirects(resp, reverse('transfer_journal'), fetch_redirect_response=False)
        # Two transactions created (OUT + IN)
        self.assertEqual(
            Transaction.objects.filter(transfer_group_id__isnull=False).count(), 2
        )

    def test_post_insufficient_stock_shows_error(self):
        """Requesting more than available → re-renders form (200), no transactions."""
        self.login_foreman()
        resp = self.client.post(reverse('add_transfer'), self._post_transfer(qty='9999.000'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            Transaction.objects.filter(transfer_group_id__isnull=False).count(), 0
        )

    def test_post_source_equals_target_shows_error(self):
        self.login_foreman()
        resp = self.client.post(
            reverse('add_transfer'),
            self._post_transfer(source=self.wh_main, target=self.wh_main)
        )
        # Re-renders with error (200) or shows message, no transactions
        self.assertFalse(
            Transaction.objects.filter(transfer_group_id__isnull=False).exists()
        )

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('add_transfer'))
        self.assertEqual(resp.status_code, 302)
