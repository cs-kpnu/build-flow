"""
Tests for warehouse/views/utils.py:
  - restrict_warehouses_qs()
  - get_multi_warehouse_balance()
  - get_stock_json()
  - log_audit()
  - ajax_materials() AJAX endpoint
  - check_access()
"""
import json
from decimal import Decimal
from django.test import TestCase, RequestFactory
from django.urls import reverse

from warehouse.models import Transaction, Order, AuditLog
from warehouse.services import inventory
from warehouse.views.utils import (
    restrict_warehouses_qs,
    get_multi_warehouse_balance,
    get_stock_json,
    log_audit,
    check_access,
)
from warehouse.tests.base import BaseTestCase


class RestrictWarehousesQsTests(BaseTestCase):
    """Tests for restrict_warehouses_qs()."""

    def setUp(self):
        super().setUp()
        # Add some transactions on different warehouses
        self.add_stock(qty=10, warehouse=self.wh_main)
        self.add_stock(qty=20, warehouse=self.wh_other, user=self.staff_user)

    def test_staff_sees_all(self):
        qs = Transaction.objects.all()
        filtered = restrict_warehouses_qs(qs, self.staff_user)
        # Staff sees all warehouses
        self.assertEqual(filtered.count(), qs.count())

    def test_superuser_sees_all(self):
        qs = Transaction.objects.all()
        filtered = restrict_warehouses_qs(qs, self.superuser)
        self.assertEqual(filtered.count(), qs.count())

    def test_foreman_sees_only_assigned(self):
        """foreman_user is assigned to wh_main only."""
        qs = Transaction.objects.all()
        filtered = restrict_warehouses_qs(qs, self.foreman_user)
        # Only transactions from wh_main
        for tx in filtered:
            self.assertEqual(tx.warehouse, self.wh_main)

    def test_foreman_excludes_other_warehouse(self):
        qs = Transaction.objects.all()
        filtered = restrict_warehouses_qs(qs, self.foreman_user)
        wh_other_txs = filtered.filter(warehouse=self.wh_other)
        self.assertEqual(wh_other_txs.count(), 0)

    def test_custom_warehouse_field(self):
        """Works with Order model using warehouse field."""
        order = self.make_order(warehouse=self.wh_main)
        Order.objects.create(warehouse=self.wh_other, status='new', created_by=self.staff_user)
        qs = Order.objects.all()
        filtered = restrict_warehouses_qs(qs, self.foreman_user, warehouse_field='warehouse')
        # Only orders on wh_main
        for order in filtered:
            self.assertEqual(order.warehouse, self.wh_main)

    def test_other_user_sees_nothing(self):
        """other_user has no warehouses assigned."""
        qs = Transaction.objects.all()
        filtered = restrict_warehouses_qs(qs, self.other_user)
        self.assertEqual(filtered.count(), 0)


class GetMultiWarehouseBalanceTests(BaseTestCase):
    """Tests for get_multi_warehouse_balance()."""

    def test_returns_dict_keyed_by_wh_id(self):
        self.add_stock(qty=10, warehouse=self.wh_main)
        result = get_multi_warehouse_balance([self.wh_main])
        self.assertIn(self.wh_main.id, result)

    def test_multiple_warehouses(self):
        self.add_stock(qty=10, warehouse=self.wh_main)
        self.add_stock(qty=20, warehouse=self.wh_site)
        result = get_multi_warehouse_balance([self.wh_main, self.wh_site])
        self.assertIn(self.wh_main.id, result)
        self.assertIn(self.wh_site.id, result)
        self.assertEqual(result[self.wh_main.id][self.mat_cement], Decimal('10.000'))
        self.assertEqual(result[self.wh_site.id][self.mat_cement], Decimal('20.000'))

    def test_empty_warehouse_list_returns_empty_dict(self):
        result = get_multi_warehouse_balance([])
        self.assertEqual(result, {})

    def test_warehouse_with_no_stock_has_empty_dict(self):
        result = get_multi_warehouse_balance([self.wh_other])
        self.assertIn(self.wh_other.id, result)
        self.assertEqual(result[self.wh_other.id], {})


class GetStockJsonTests(BaseTestCase):
    """Tests for get_stock_json()."""

    def setUp(self):
        super().setUp()
        self.add_stock(qty=10, warehouse=self.wh_main)
        self.add_stock(qty=20, warehouse=self.wh_site)

    def test_returns_valid_json_string(self):
        result = get_stock_json(self.staff_user)
        # Should not raise
        parsed = json.loads(result)
        self.assertIsInstance(parsed, dict)

    def test_staff_sees_all_warehouses(self):
        result = json.loads(get_stock_json(self.staff_user))
        # All three warehouses should be present
        self.assertIn(str(self.wh_main.id), {str(k) for k in result.keys()})
        self.assertIn(str(self.wh_site.id), {str(k) for k in result.keys()})

    def test_foreman_sees_only_own_warehouse(self):
        result = json.loads(get_stock_json(self.foreman_user))
        wh_ids = {int(k) for k in result.keys()}
        self.assertIn(self.wh_main.id, wh_ids)
        # wh_other should NOT be present (foreman not assigned)
        self.assertNotIn(self.wh_other.id, wh_ids)

    def test_json_contains_items_dict(self):
        result = json.loads(get_stock_json(self.staff_user))
        for wh_id, wh_data in result.items():
            self.assertIn('name', wh_data)
            self.assertIn('items', wh_data)


class LogAuditTests(BaseTestCase):
    """Tests for log_audit()."""

    def test_creates_audit_log_entry(self):
        self.login_staff()
        resp = self.client.get(reverse('manager_dashboard'))
        # Manually call log_audit via a POST to add_transaction (which internally calls it)
        # Instead, directly call log_audit with a fake request
        factory = RequestFactory()
        request = factory.get('/', REMOTE_ADDR='127.0.0.1')
        request.user = self.staff_user

        initial_count = AuditLog.objects.count()
        log_audit(request, 'CREATE')
        self.assertGreater(AuditLog.objects.count(), initial_count)

    def test_does_not_raise_on_none_request(self):
        try:
            log_audit(None, 'CREATE')
        except Exception as e:
            self.fail(f"log_audit(None, 'CREATE') raised: {e}")

    def test_extracts_ip_from_x_forwarded_for(self):
        factory = RequestFactory()
        request = factory.get('/', HTTP_X_FORWARDED_FOR='1.2.3.4, 5.6.7.8')
        request.user = self.staff_user
        log_audit(request, 'CREATE')
        entry = AuditLog.objects.filter(user=self.staff_user, action_type='CREATE').last()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.ip_address, '1.2.3.4')

    def test_uses_remote_addr_when_no_forwarded_for(self):
        factory = RequestFactory()
        request = factory.get('/', REMOTE_ADDR='9.9.9.9')
        request.user = self.staff_user
        log_audit(request, 'UPDATE')
        entry = AuditLog.objects.filter(user=self.staff_user, action_type='UPDATE').last()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.ip_address, '9.9.9.9')


class CheckAccessTests(BaseTestCase):
    """Tests for check_access()."""

    def test_staff_always_has_access(self):
        self.assertTrue(check_access(self.staff_user, self.wh_other))

    def test_superuser_always_has_access(self):
        self.assertTrue(check_access(self.superuser, self.wh_other))

    def test_foreman_has_access_to_assigned_warehouse(self):
        self.assertTrue(check_access(self.foreman_user, self.wh_main))

    def test_foreman_no_access_to_unassigned_warehouse(self):
        self.assertFalse(check_access(self.foreman_user, self.wh_other))

    def test_other_user_no_access_to_any_warehouse(self):
        self.assertFalse(check_access(self.other_user, self.wh_main))

    def test_accepts_warehouse_id_instead_of_object(self):
        self.assertTrue(check_access(self.foreman_user, self.wh_main.id))


class AjaxMaterialsEndpointTests(BaseTestCase):
    """Tests for ajax_materials() endpoint."""

    def setUp(self):
        super().setUp()
        self.url = reverse('ajax_materials')

    def test_requires_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)

    def test_returns_200_with_items(self):
        self.login_foreman()
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('items', data)
        self.assertGreater(len(data['items']), 0)

    def test_search_filters_by_name(self):
        self.login_foreman()
        resp = self.client.get(self.url, {'q': 'Cement'})
        data = resp.json()
        names = [item['name'] for item in data['items']]
        self.assertIn('Cement', names)
        self.assertNotIn('Brick', names)

    def test_search_by_article(self):
        self.login_foreman()
        resp = self.client.get(self.url, {'q': 'CEM'})
        data = resp.json()
        names = [item['name'] for item in data['items']]
        self.assertIn('Cement', names)

    def test_empty_query_returns_all(self):
        self.login_foreman()
        resp = self.client.get(self.url)
        data = resp.json()
        self.assertGreaterEqual(len(data['items']), 2)

    def test_term_param_also_works(self):
        self.login_foreman()
        resp = self.client.get(self.url, {'term': 'Brick'})
        data = resp.json()
        names = [item['name'] for item in data['items']]
        self.assertIn('Brick', names)
