"""
Tests for views/foreman.py:
  - foreman_order_detail
  - foreman_storage_view
  - writeoff_history_view
  - delivery_history_view
"""
from django.test import TestCase
from django.urls import reverse

from warehouse.models import Order, OrderComment, Transaction
from warehouse.services import inventory
from warehouse.tests.base import BaseTestCase


class ForemanOrderDetailTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.order = self.make_order(status='new', user=self.foreman_user)

    def test_owner_gets_200(self):
        self.login_foreman()
        resp = self.client.get(reverse('foreman_order_detail', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_staff_with_warehouse_access_gets_200(self):
        self.login_staff()
        resp = self.client.get(reverse('foreman_order_detail', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_other_user_no_access_gets_403(self):
        """other_user has no warehouse access and is not owner."""
        self.client.force_login(self.other_user)
        resp = self.client.get(reverse('foreman_order_detail', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_post_comment_adds_comment(self):
        self.login_foreman()
        resp = self.client.post(
            reverse('foreman_order_detail', args=[self.order.pk]),
            {'comment_text': 'Test comment from foreman'}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            OrderComment.objects.filter(
                order=self.order, text='Test comment from foreman'
            ).exists()
        )

    def test_post_empty_comment_does_not_create(self):
        self.login_foreman()
        initial_count = OrderComment.objects.filter(order=self.order).count()
        self.client.post(
            reverse('foreman_order_detail', args=[self.order.pk]),
            {'comment_text': ''}
        )
        self.assertEqual(
            OrderComment.objects.filter(order=self.order).count(),
            initial_count
        )

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('foreman_order_detail', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 302)

    def test_404_for_nonexistent_order(self):
        self.login_foreman()
        resp = self.client.get(reverse('foreman_order_detail', args=[99999]))
        self.assertEqual(resp.status_code, 404)


class ForemanStorageViewTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.add_stock(qty=50)

    def test_foreman_gets_200(self):
        self.login_foreman()
        resp = self.client.get(reverse('foreman_storage'))
        self.assertEqual(resp.status_code, 200)

    def test_context_has_warehouse_and_stock(self):
        self.login_foreman()
        resp = self.client.get(reverse('foreman_storage'))
        self.assertIn('warehouse', resp.context)
        self.assertIn('stock', resp.context)

    def test_uses_session_active_warehouse(self):
        self.login_foreman()
        session = self.client.session
        session['active_warehouse_id'] = self.wh_main.pk
        session.save()
        resp = self.client.get(reverse('foreman_storage'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['warehouse'], self.wh_main)

    def test_falls_back_to_first_warehouse_when_no_session(self):
        self.login_foreman()
        resp = self.client.get(reverse('foreman_storage'))
        # Should pick foreman's only warehouse (wh_main)
        self.assertEqual(resp.context['warehouse'], self.wh_main)

    def test_no_warehouses_renders_without_crash(self):
        """other_user has no warehouses — should not crash."""
        self.client.force_login(self.other_user)
        resp = self.client.get(reverse('foreman_storage'))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context.get('warehouse'))

    def test_stock_items_present_after_adding_stock(self):
        self.login_foreman()
        resp = self.client.get(reverse('foreman_storage'))
        stock = resp.context['stock']
        self.assertGreater(len(stock), 0)
        names = [item['name'] for item in stock]
        self.assertIn('Cement', names)

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('foreman_storage'))
        self.assertEqual(resp.status_code, 302)


class WriteoffHistoryViewTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.add_stock(qty=100)
        # Create an OUT transaction on wh_main
        inventory.create_writeoff(
            self.mat_cement, self.wh_main, 30, self.foreman_user, description='Test writeoff'
        )

    def test_foreman_gets_200(self):
        self.login_foreman()
        resp = self.client.get(reverse('writeoff_history'))
        self.assertEqual(resp.status_code, 200)

    def test_context_contains_writeoffs(self):
        self.login_foreman()
        resp = self.client.get(reverse('writeoff_history'))
        self.assertIn('writeoffs', resp.context)

    def test_foreman_sees_own_warehouse_writeoffs(self):
        self.login_foreman()
        resp = self.client.get(reverse('writeoff_history'))
        writeoffs = list(resp.context['writeoffs'])
        wh_ids = {tx.warehouse_id for tx in writeoffs}
        self.assertIn(self.wh_main.pk, wh_ids)

    def test_foreman_excludes_other_warehouse(self):
        """Add writeoff to wh_other; foreman should not see it."""
        # Staff adds stock + writeoff on wh_other
        inventory.create_incoming(
            self.mat_cement, self.wh_other, 50, self.staff_user
        )
        inventory.create_writeoff(
            self.mat_cement, self.wh_other, 10, self.staff_user, description='Other writeoff'
        )
        self.login_foreman()
        resp = self.client.get(reverse('writeoff_history'))
        writeoffs = list(resp.context['writeoffs'])
        wh_ids = {tx.warehouse_id for tx in writeoffs}
        self.assertNotIn(self.wh_other.pk, wh_ids)

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('writeoff_history'))
        self.assertEqual(resp.status_code, 302)


class DeliveryHistoryViewTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        # Create an IN transaction on wh_main
        self.add_stock(qty=40)

    def test_foreman_gets_200(self):
        self.login_foreman()
        resp = self.client.get(reverse('delivery_history'))
        self.assertEqual(resp.status_code, 200)

    def test_context_contains_deliveries(self):
        self.login_foreman()
        resp = self.client.get(reverse('delivery_history'))
        self.assertIn('deliveries', resp.context)

    def test_foreman_sees_own_warehouse_deliveries(self):
        self.login_foreman()
        resp = self.client.get(reverse('delivery_history'))
        deliveries = list(resp.context['deliveries'])
        wh_ids = {tx.warehouse_id for tx in deliveries}
        self.assertIn(self.wh_main.pk, wh_ids)

    def test_foreman_excludes_other_warehouse_deliveries(self):
        """Deliveries on wh_other should not appear for foreman."""
        inventory.create_incoming(
            self.mat_cement, self.wh_other, 50, self.staff_user
        )
        self.login_foreman()
        resp = self.client.get(reverse('delivery_history'))
        deliveries = list(resp.context['deliveries'])
        wh_ids = {tx.warehouse_id for tx in deliveries}
        self.assertNotIn(self.wh_other.pk, wh_ids)

    def test_pagination_works(self):
        # Add many deliveries
        for _ in range(5):
            self.add_stock(qty=1)
        self.login_foreman()
        resp = self.client.get(reverse('delivery_history'))
        self.assertEqual(resp.status_code, 200)

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('delivery_history'))
        self.assertEqual(resp.status_code, 302)
