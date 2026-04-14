"""
Tests for views/orders.py:
  - order_list
  - create_order
  - edit_order
  - delete_order
  - logistics_monitor
  - mark_order_shipped
  - confirm_receipt
  - check_order_duplicates
  - print_order_pdf
"""
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from django.core.cache import cache

from warehouse.models import Order, OrderItem, Transaction
from warehouse.services import inventory
from warehouse.tests.base import BaseTestCase


class OrderListViewTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.make_order(status='new')
        self.make_order(status='approved')

    def test_returns_200(self):
        self.login_foreman()
        resp = self.client.get(reverse('order_list'))
        self.assertEqual(resp.status_code, 200)

    def test_status_filter(self):
        self.login_foreman()
        resp = self.client.get(reverse('order_list'), {'status': 'new'})
        self.assertEqual(resp.status_code, 200)
        orders = list(resp.context['orders'])
        for o in orders:
            self.assertEqual(o.status, 'new')

    def test_excel_export_returns_xlsx(self):
        self.login_foreman()
        resp = self.client.get(reverse('order_list'), {'export': 'excel'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('spreadsheetml', resp['Content-Type'])
        self.assertIn('attachment', resp['Content-Disposition'])

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('order_list'))
        self.assertEqual(resp.status_code, 302)


class CreateOrderViewTests(BaseTestCase):

    def _formset_data(self, material, qty='5.000'):
        """Build minimal valid formset POST data."""
        return {
            'items-TOTAL_FORMS': '1',
            'items-INITIAL_FORMS': '0',
            'items-MIN_NUM_FORMS': '0',
            'items-MAX_NUM_FORMS': '1000',
            'items-0-material': material.pk,
            'items-0-quantity': qty,
            'items-0-DELETE': '',
        }

    def _order_data(self, warehouse):
        return {
            'warehouse': warehouse.pk,
            'priority': 'medium',
            'note': '',
        }

    def test_get_renders_form(self):
        self.login_foreman()
        resp = self.client.get(reverse('create_order'))
        self.assertEqual(resp.status_code, 200)

    def test_post_valid_foreman_redirects_to_foreman_detail(self):
        self.login_foreman()
        data = {**self._order_data(self.wh_main), **self._formset_data(self.mat_cement)}
        resp = self.client.post(reverse('create_order'), data)
        # Should redirect to foreman_order_detail
        self.assertEqual(resp.status_code, 302)
        self.assertIn('foreman/order/', resp['Location'])
        self.assertTrue(Order.objects.filter(created_by=self.foreman_user).exists())

    def test_post_valid_staff_redirects_to_manager_detail(self):
        self.login_staff()
        data = {**self._order_data(self.wh_main), **self._formset_data(self.mat_cement)}
        resp = self.client.post(reverse('create_order'), data)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('manager/order/', resp['Location'])

    def test_post_invalid_stays_on_form(self):
        self.login_foreman()
        # Missing required 'warehouse' field → form invalid → re-renders (200)
        data = {
            'priority': 'medium',
            'note': '',
            'items-TOTAL_FORMS': '1',
            'items-INITIAL_FORMS': '0',
            'items-MIN_NUM_FORMS': '0',
            'items-MAX_NUM_FORMS': '1000',
            'items-0-material': self.mat_cement.pk,
            'items-0-quantity': '5.000',
            'items-0-DELETE': '',
        }
        resp = self.client.post(reverse('create_order'), data)
        self.assertEqual(resp.status_code, 200)

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('create_order'))
        self.assertEqual(resp.status_code, 302)


class EditOrderViewTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.order = self.make_order(status='new', user=self.foreman_user)

    def _formset_data(self, order=None):
        target = order or self.order
        item = target.items.first()
        return {
            'items-TOTAL_FORMS': '1',
            'items-INITIAL_FORMS': '1',
            'items-MIN_NUM_FORMS': '0',
            'items-MAX_NUM_FORMS': '1000',
            'items-0-id': item.pk,
            'items-0-order': target.pk,
            'items-0-material': item.material.pk,
            'items-0-quantity': '10.000',
            'items-0-DELETE': '',
        }

    def test_get_returns_200_for_owner(self):
        self.login_foreman()
        resp = self.client.get(reverse('edit_order', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_non_owner_non_staff_gets_403(self):
        self.client.force_login(self.other_user)
        resp = self.client.get(reverse('edit_order', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_staff_can_edit_any_order(self):
        self.login_staff()
        resp = self.client.get(reverse('edit_order', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_completed_order_redirects_not_editable(self):
        self.order.status = 'completed'
        self.order.save()
        self.login_foreman()
        resp = self.client.get(reverse('edit_order', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 302)


class DeleteOrderViewTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.order = self.make_order(status='new', user=self.foreman_user)

    def test_owner_can_delete_new_order(self):
        self.login_foreman()
        resp = self.client.post(reverse('delete_order', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Order.objects.filter(pk=self.order.pk).exists())

    def test_non_owner_gets_403(self):
        self.client.force_login(self.other_user)
        resp = self.client.post(reverse('delete_order', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Order.objects.filter(pk=self.order.pk).exists())

    def test_non_new_status_cannot_be_deleted(self):
        self.order.status = 'approved'
        self.order.save()
        self.login_foreman()
        resp = self.client.post(reverse('delete_order', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 302)
        # Order should still exist
        self.assertTrue(Order.objects.filter(pk=self.order.pk).exists())


class LogisticsViewTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.make_order(status='purchasing')
        self.make_order(status='transit')

    def test_non_staff_gets_403(self):
        self.login_foreman()
        resp = self.client.get(reverse('logistics_monitor'))
        self.assertEqual(resp.status_code, 403)

    def test_staff_gets_200(self):
        self.login_staff()
        resp = self.client.get(reverse('logistics_monitor'))
        self.assertEqual(resp.status_code, 200)

    def test_context_contains_purchasing_and_transit(self):
        self.login_staff()
        resp = self.client.get(reverse('logistics_monitor'))
        self.assertIn('purchasing_orders', resp.context)
        self.assertIn('transit_orders', resp.context)


class MarkOrderShippedTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.order = self.make_order(status='purchasing')

    def test_staff_changes_status_to_transit(self):
        self.login_staff()
        resp = self.client.post(reverse('mark_order_shipped', args=[self.order.pk]), {
            'driver_phone': '0501234567',
            'vehicle_number': 'AA1234BB',
        })
        self.assertEqual(resp.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'transit')

    def test_non_staff_gets_403(self):
        self.login_foreman()
        resp = self.client.post(reverse('mark_order_shipped', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 403)


class ConfirmReceiptViewTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.order = self.make_order(status='purchasing', user=self.foreman_user)
        self.item = self.order.items.first()

    def test_get_renders_form_for_allowed_user(self):
        self.login_foreman()
        resp = self.client.get(reverse('confirm_receipt', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_post_completes_order(self):
        self.login_foreman()
        resp = self.client.post(reverse('confirm_receipt', args=[self.order.pk]), {
            f'item_qty_{self.item.pk}': '10',
        })
        self.assertEqual(resp.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'completed')

    def test_transaction_created_on_receipt(self):
        self.login_foreman()
        self.client.post(reverse('confirm_receipt', args=[self.order.pk]), {
            f'item_qty_{self.item.pk}': '10',
        })
        self.assertTrue(
            Transaction.objects.filter(order=self.order, transaction_type='IN').exists()
        )

    def test_other_user_no_warehouse_access_gets_403(self):
        self.client.force_login(self.other_user)
        resp = self.client.get(reverse('confirm_receipt', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_wrong_status_redirects_with_warning(self):
        self.order.status = 'new'
        self.order.save()
        self.login_foreman()
        resp = self.client.get(reverse('confirm_receipt', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 302)


class CheckOrderDuplicatesTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        cache.clear()
        self.login_foreman()
        self.url = reverse('check_order_duplicates')

    def test_no_recent_orders_returns_false(self):
        resp = self.client.get(self.url, {'warehouse': self.wh_main.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()['exists'])

    def test_recent_order_returns_exists_true(self):
        self.make_order(status='new', user=self.foreman_user)
        resp = self.client.get(self.url, {'warehouse': self.wh_main.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['exists'])

    def test_missing_warehouse_returns_false(self):
        resp = self.client.get(self.url)
        self.assertFalse(resp.json()['exists'])


class PrintOrderPdfTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.order = self.make_order(user=self.foreman_user)

    def test_staff_can_print(self):
        self.login_staff()
        resp = self.client.get(reverse('print_order_pdf', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_order_owner_can_print(self):
        self.login_foreman()
        resp = self.client.get(reverse('print_order_pdf', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_non_owner_no_access_gets_403(self):
        self.client.force_login(self.other_user)
        resp = self.client.get(reverse('print_order_pdf', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 403)
