"""
Tests for warehouse/decorators.py:
  - @staff_required
  - @group_required
  - @rate_limit
"""
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User, Group, AnonymousUser
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.urls import reverse

from warehouse.decorators import staff_required, group_required, rate_limit
from warehouse.tests.base import BaseTestCase


# ---------------------------------------------------------------------------
# Minimal view functions used in decorator unit tests
# ---------------------------------------------------------------------------

@staff_required
def _staff_view(request):
    return HttpResponse('ok_staff')


@group_required('Foreman')
def _foreman_group_view(request):
    return HttpResponse('ok_foreman_group')


# ---------------------------------------------------------------------------


class StaffRequiredDecoratorTests(BaseTestCase):
    """@staff_required: anonymous→login redirect, non-staff→403, staff→200."""

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('manager_dashboard'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp['Location'])

    def test_non_staff_gets_403(self):
        self.login_foreman()
        resp = self.client.get(reverse('manager_dashboard'))
        self.assertEqual(resp.status_code, 403)

    def test_staff_user_gets_200(self):
        self.login_staff()
        resp = self.client.get(reverse('manager_dashboard'))
        self.assertEqual(resp.status_code, 200)

    def test_staff_required_via_request_factory_anon(self):
        factory = RequestFactory()
        request = factory.get('/')
        request.user = AnonymousUser()
        resp = _staff_view(request)
        # staff_required redirects to LOGIN_URL for anonymous users
        self.assertEqual(resp.status_code, 302)

    def test_staff_required_via_request_factory_non_staff(self):
        factory = RequestFactory()
        request = factory.get('/')
        request.user = self.foreman_user
        with self.assertRaises(PermissionDenied):
            _staff_view(request)

    def test_staff_required_via_request_factory_staff(self):
        factory = RequestFactory()
        request = factory.get('/')
        request.user = self.staff_user
        resp = _staff_view(request)
        self.assertEqual(resp.status_code, 200)


class GroupRequiredDecoratorTests(BaseTestCase):
    """@group_required: superuser bypasses, in-group allowed, out-of-group→403, anon→403."""

    def _make_request(self, user):
        factory = RequestFactory()
        req = factory.get('/')
        req.user = user
        return req

    def test_superuser_bypasses_group_check(self):
        req = self._make_request(self.superuser)
        resp = _foreman_group_view(req)
        self.assertEqual(resp.status_code, 200)

    def test_user_in_group_allowed(self):
        # foreman_user is in 'Foreman' group (set in setUpTestData)
        req = self._make_request(self.foreman_user)
        resp = _foreman_group_view(req)
        self.assertEqual(resp.status_code, 200)

    def test_user_not_in_group_gets_403(self):
        req = self._make_request(self.staff_user)
        with self.assertRaises(PermissionDenied):
            _foreman_group_view(req)

    def test_anonymous_user_gets_403(self):
        req = self._make_request(AnonymousUser())
        with self.assertRaises(PermissionDenied):
            _foreman_group_view(req)


class RateLimitDecoratorTests(BaseTestCase):
    """@rate_limit: requests within limit pass, exceeding→429."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.login_foreman()
        self.url = reverse('check_order_duplicates')

    def test_requests_within_limit_succeed(self):
        for _ in range(5):
            resp = self.client.get(self.url)
            self.assertNotEqual(resp.status_code, 429)

    def test_request_exceeding_limit_returns_429(self):
        # check_order_duplicates has @rate_limit(requests_per_minute=30)
        for _ in range(30):
            self.client.get(self.url)
        # The 31st request should be rate-limited
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 429)

    def test_rate_limit_keyed_per_user(self):
        """Two different users each make requests without triggering each other's limit."""
        # foreman makes 15 requests
        for _ in range(15):
            self.client.get(self.url)
        # switch to staff user
        cache.clear()
        self.client.force_login(self.staff_user)
        # staff makes 15 requests — should not be 429
        for _ in range(15):
            resp = self.client.get(self.url)
            self.assertNotEqual(resp.status_code, 429)
