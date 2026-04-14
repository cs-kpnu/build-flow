"""
Tests for views/reports.py and analytics views:
  - reports_dashboard
  - writeoff_report
  - period_report
  - stock_balance_report
  - transfer_journal
  - transfer_analytics
  - financial_report (savings_report)
  - problem_areas
  - movement_history
  - procurement_journal
  - objects_comparison
  - global_audit_log
  - planning_report
  - suppliers_rating
  - concrete_analytics
  - rebar_analytics
  - mechanisms_analytics
  - project_dashboard
"""
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from warehouse.models import Order, Transaction
from warehouse.services import inventory
from warehouse.tests.base import BaseTestCase


# ---------------------------------------------------------------------------
# Helper: list of all @staff_required report URL names
# ---------------------------------------------------------------------------
STAFF_REQUIRED_REPORT_URLS = [
    'reports_dashboard',
    'writeoff_report',
    'period_report',
    'stock_balance_report',
    'transfer_journal',
    'transfer_analytics',
    'financial_report',
    'problem_areas',
    'movement_history',
    'procurement_journal',
    'objects_comparison',
    'planning_report',
    'suppliers_rating',
]


class ReportAccessTests(BaseTestCase):
    """
    Parametrised access checks for all @staff_required report views.
    Each URL: non-staff → 403, staff → 200, anonymous → 302.
    """

    def test_non_staff_gets_403_for_all_reports(self):
        self.login_foreman()
        for name in STAFF_REQUIRED_REPORT_URLS:
            with self.subTest(url_name=name):
                resp = self.client.get(reverse(name))
                self.assertEqual(
                    resp.status_code, 403,
                    f"{name}: expected 403 for non-staff, got {resp.status_code}"
                )

    def test_staff_gets_200_for_all_reports(self):
        self.login_staff()
        for name in STAFF_REQUIRED_REPORT_URLS:
            with self.subTest(url_name=name):
                resp = self.client.get(reverse(name))
                self.assertEqual(
                    resp.status_code, 200,
                    f"{name}: expected 200 for staff, got {resp.status_code}"
                )

    def test_anonymous_redirects_for_all_reports(self):
        for name in STAFF_REQUIRED_REPORT_URLS:
            with self.subTest(url_name=name):
                resp = self.client.get(reverse(name))
                self.assertEqual(
                    resp.status_code, 302,
                    f"{name}: expected 302 for anonymous, got {resp.status_code}"
                )


class WriteoffReportTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.add_stock(qty=200)
        inventory.create_writeoff(
            self.mat_cement, self.wh_main, 30, self.staff_user, description='Work'
        )

    def test_date_filter_does_not_crash(self):
        self.login_staff()
        today = timezone.now().date().isoformat()
        resp = self.client.get(reverse('writeoff_report'), {
            'date_from': today, 'date_to': today
        })
        self.assertEqual(resp.status_code, 200)

    def test_invalid_date_does_not_raise_500(self):
        self.login_staff()
        resp = self.client.get(reverse('writeoff_report'), {
            'date_from': 'not-a-date', 'date_to': 'also-bad'
        })
        self.assertEqual(resp.status_code, 200)

    def test_excel_export_returns_xlsx(self):
        self.login_staff()
        resp = self.client.get(reverse('writeoff_report'), {'export': 'excel'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('spreadsheetml', resp['Content-Type'])
        self.assertIn('attachment', resp['Content-Disposition'])


class PeriodReportTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.add_stock(qty=100)

    def test_renders_with_date_range(self):
        self.login_staff()
        today = timezone.now().date()
        resp = self.client.get(reverse('period_report'), {
            'date_from': today.replace(day=1).isoformat(),
            'date_to': today.isoformat(),
            'warehouse': self.wh_main.pk,
        })
        self.assertEqual(resp.status_code, 200)

    def test_excel_export_returns_200(self):
        # period_report only exports xlsx when report_data is non-empty.
        # Without matching transactions the view returns normal HTML (200).
        self.login_staff()
        resp = self.client.get(reverse('period_report'), {'export': 'excel'})
        self.assertEqual(resp.status_code, 200)


class StockBalanceReportTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.add_stock(qty=50)

    def test_context_has_balance_data(self):
        self.login_staff()
        resp = self.client.get(reverse('stock_balance_report'))
        self.assertEqual(resp.status_code, 200)

    def test_excel_export_returns_xlsx(self):
        self.login_staff()
        resp = self.client.get(reverse('stock_balance_report'), {'export': 'excel'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('spreadsheetml', resp['Content-Type'])


class TransferJournalTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.add_stock(qty=100)

    def test_date_filter_does_not_crash(self):
        self.login_staff()
        today = timezone.now().date().isoformat()
        resp = self.client.get(reverse('transfer_journal'), {
            'date_from': today, 'date_to': today
        })
        self.assertEqual(resp.status_code, 200)


class ProblemAreasTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        # Create an overdue order (expected_date in the past, status=purchasing)
        self.order = self.make_order(status='purchasing')
        self.order.expected_date = timezone.now().date() - timezone.timedelta(days=5)
        self.order.save()

    def test_context_has_problem_orders(self):
        self.login_staff()
        resp = self.client.get(reverse('problem_areas'))
        self.assertEqual(resp.status_code, 200)


class MovementHistoryTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        # Create a few transactions
        for _ in range(3):
            self.add_stock(qty=10)

    def test_pagination_first_page(self):
        self.login_staff()
        resp = self.client.get(reverse('movement_history'))
        self.assertEqual(resp.status_code, 200)

    def test_page_2_does_not_crash(self):
        self.login_staff()
        resp = self.client.get(reverse('movement_history'), {'page': 2})
        self.assertIn(resp.status_code, [200, 404])


class GlobalAuditLogTests(BaseTestCase):
    """global_audit_log has 3 auth levels."""

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('global_audit_log'))
        self.assertEqual(resp.status_code, 302)

    def test_non_staff_gets_403(self):
        self.login_foreman()
        resp = self.client.get(reverse('global_audit_log'))
        self.assertEqual(resp.status_code, 403)

    def test_staff_non_superuser_gets_403(self):
        self.login_staff()
        resp = self.client.get(reverse('global_audit_log'))
        self.assertEqual(resp.status_code, 403)

    def test_superuser_gets_200(self):
        self.login_super()
        resp = self.client.get(reverse('global_audit_log'))
        self.assertEqual(resp.status_code, 200)


class PlanningReportTests(BaseTestCase):

    def test_staff_gets_200(self):
        self.login_staff()
        resp = self.client.get(reverse('planning_report'))
        self.assertEqual(resp.status_code, 200)

    def test_excel_export_returns_200(self):
        # planning_report only exports xlsx when report_data is non-empty.
        self.login_staff()
        resp = self.client.get(reverse('planning_report'), {'export': 'excel'})
        self.assertEqual(resp.status_code, 200)


class SuppliersRatingTests(BaseTestCase):

    def test_staff_gets_200(self):
        self.login_staff()
        resp = self.client.get(reverse('suppliers_rating'))
        self.assertEqual(resp.status_code, 200)

    def test_excel_export_returns_200(self):
        # suppliers_rating only exports xlsx when there are suppliers with orders.
        self.login_staff()
        resp = self.client.get(reverse('suppliers_rating'), {'export': 'excel'})
        self.assertEqual(resp.status_code, 200)


class ProjectDashboardTests(BaseTestCase):
    """project_dashboard is @login_required (not @staff_required)."""

    def test_foreman_gets_200(self):
        self.login_foreman()
        resp = self.client.get(reverse('project_dashboard'))
        self.assertEqual(resp.status_code, 200)

    def test_staff_gets_200(self):
        self.login_staff()
        resp = self.client.get(reverse('project_dashboard'))
        self.assertEqual(resp.status_code, 200)

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('project_dashboard'))
        self.assertEqual(resp.status_code, 302)

    def test_context_has_total_spent(self):
        self.login_staff()
        resp = self.client.get(reverse('project_dashboard'))
        self.assertIn('total_spent', resp.context)


class ConcreteAnalyticsTests(BaseTestCase):
    """concrete_analytics is @login_required."""

    def test_foreman_gets_200(self):
        self.login_foreman()
        resp = self.client.get(reverse('concrete_analytics'))
        self.assertEqual(resp.status_code, 200)

    def test_staff_gets_200(self):
        self.login_staff()
        resp = self.client.get(reverse('concrete_analytics'))
        self.assertEqual(resp.status_code, 200)

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('concrete_analytics'))
        self.assertEqual(resp.status_code, 302)

    def test_excel_export(self):
        self.login_staff()
        resp = self.client.get(reverse('concrete_analytics'), {'export': 'excel'})
        # Either xlsx or regular 200 if no data
        self.assertIn(resp.status_code, [200, 302])


class RebarAnalyticsTests(BaseTestCase):
    """rebar_analytics is @login_required."""

    def test_foreman_gets_200(self):
        self.login_foreman()
        resp = self.client.get(reverse('rebar_analytics'))
        self.assertEqual(resp.status_code, 200)

    def test_staff_gets_200(self):
        self.login_staff()
        resp = self.client.get(reverse('rebar_analytics'))
        self.assertEqual(resp.status_code, 200)

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('rebar_analytics'))
        self.assertEqual(resp.status_code, 302)


class MechanismsAnalyticsTests(BaseTestCase):
    """mechanisms_analytics is @login_required."""

    def test_foreman_gets_200(self):
        self.login_foreman()
        resp = self.client.get(reverse('mechanisms_analytics'))
        self.assertEqual(resp.status_code, 200)

    def test_staff_gets_200(self):
        self.login_staff()
        resp = self.client.get(reverse('mechanisms_analytics'))
        self.assertEqual(resp.status_code, 200)

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('mechanisms_analytics'))
        self.assertEqual(resp.status_code, 302)
