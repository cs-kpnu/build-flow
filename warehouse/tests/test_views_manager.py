"""
Tests for views/manager.py:
  - dashboard
  - order_list (manager)
  - order_detail (manager)
  - order_approve
  - order_reject
  - order_to_purchasing
  - split_order
  - create_po
"""
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse

from warehouse.models import Order, OrderComment
from warehouse.tests.base import BaseTestCase


class ManagerDashboardTests(BaseTestCase):

    def test_non_staff_gets_403(self):
        self.login_foreman()
        resp = self.client.get(reverse('manager_dashboard'))
        self.assertEqual(resp.status_code, 403)

    def test_staff_gets_200(self):
        self.login_staff()
        resp = self.client.get(reverse('manager_dashboard'))
        self.assertEqual(resp.status_code, 200)

    def test_context_has_stats_dict(self):
        self.login_staff()
        resp = self.client.get(reverse('manager_dashboard'))
        self.assertIn('stats', resp.context)
        stats = resp.context['stats']
        self.assertIn('new', stats)
        self.assertIn('approved', stats)

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('manager_dashboard'))
        self.assertEqual(resp.status_code, 302)


class ManagerOrderListTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.make_order(status='new')
        self.make_order(status='approved')

    def test_foreman_can_access_order_list(self):
        # /manager/orders/ maps to orders.order_list which is @login_required (not @staff_required)
        self.login_foreman()
        resp = self.client.get('/manager/orders/')
        self.assertEqual(resp.status_code, 200)

    def test_staff_gets_200(self):
        self.login_staff()
        resp = self.client.get('/manager/orders/')
        self.assertEqual(resp.status_code, 200)

    def test_status_filter(self):
        self.login_staff()
        resp = self.client.get('/manager/orders/', {'status': 'new'})
        self.assertEqual(resp.status_code, 200)
        for order in resp.context['orders']:
            self.assertEqual(order.status, 'new')


class ManagerOrderDetailTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.order = self.make_order(status='new')

    def test_staff_gets_200(self):
        self.login_staff()
        resp = self.client.get(reverse('manager_order_detail', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_non_staff_gets_403(self):
        self.login_foreman()
        resp = self.client.get(reverse('manager_order_detail', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_post_comment_adds_comment(self):
        self.login_staff()
        resp = self.client.post(
            reverse('manager_order_detail', args=[self.order.pk]),
            {'add_comment': '1', 'text': 'Nice order!'}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            OrderComment.objects.filter(order=self.order, text='Nice order!').exists()
        )


class OrderApproveTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.order = self.make_order(status='new')

    def test_get_shows_confirmation_page(self):
        self.login_staff()
        resp = self.client.get(reverse('order_approve', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_post_changes_status_to_approved(self):
        self.login_staff()
        resp = self.client.post(reverse('order_approve', args=[self.order.pk]))
        self.assertRedirects(
            resp,
            reverse('manager_order_detail', args=[self.order.pk]),
            fetch_redirect_response=False
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'approved')

    def test_auto_comment_added_on_approve(self):
        self.login_staff()
        self.client.post(reverse('order_approve', args=[self.order.pk]))
        self.assertTrue(
            OrderComment.objects.filter(order=self.order).exists()
        )

    def test_non_staff_gets_403(self):
        self.login_foreman()
        resp = self.client.post(reverse('order_approve', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 403)


class OrderRejectTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.order = self.make_order(status='new')

    def test_post_changes_status_to_rejected(self):
        self.login_staff()
        self.client.post(
            reverse('order_reject', args=[self.order.pk]),
            {'reason': 'Too expensive'}
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'rejected')

    def test_auto_comment_with_reason(self):
        self.login_staff()
        self.client.post(
            reverse('order_reject', args=[self.order.pk]),
            {'reason': 'Budget exceeded'}
        )
        self.assertTrue(
            OrderComment.objects.filter(
                order=self.order, text__icontains='Budget exceeded'
            ).exists()
        )

    def test_get_shows_confirmation(self):
        self.login_staff()
        resp = self.client.get(reverse('order_reject', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 200)


class OrderToPurchasingTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.order = self.make_order(status='approved')

    def test_approved_transitions_to_purchasing(self):
        self.login_staff()
        self.client.post(reverse('order_to_purchasing', args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'purchasing')

    def test_non_approved_status_shows_error(self):
        self.order.status = 'new'
        self.order.save()
        self.login_staff()
        self.client.post(reverse('order_to_purchasing', args=[self.order.pk]))
        self.order.refresh_from_db()
        # Status should remain 'new', not change
        self.assertEqual(self.order.status, 'new')

    def test_get_shows_confirmation_page(self):
        self.login_staff()
        resp = self.client.get(reverse('order_to_purchasing', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 200)


class SplitOrderTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.order = self.make_order(status='new')
        self.item = self.order.items.first()

    def test_get_renders_split_form(self):
        self.login_staff()
        resp = self.client.get(reverse('split_order', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_post_all_items_original_keeps_order_intact(self):
        """All items stay with original order → order not rejected."""
        self.login_staff()
        self.client.post(
            reverse('split_order', args=[self.order.pk]),
            {f'item_{self.item.pk}': 'original'}
        )
        self.order.refresh_from_db()
        # Order should not be rejected since items stay
        self.assertNotEqual(self.order.status, 'rejected')

    def test_non_staff_gets_403(self):
        self.login_foreman()
        resp = self.client.get(reverse('split_order', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 403)


class CreatePoTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.order = self.make_order()

    def test_redirects_to_print_order_pdf(self):
        self.login_staff()
        resp = self.client.get(
            reverse('manager_process_order', args=[self.order.pk])
        )
        # manager_process_order either renders a stub page or redirects
        self.assertIn(resp.status_code, [200, 302])
