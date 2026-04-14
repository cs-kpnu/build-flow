"""
Tests for views/general.py and views/home.py:
  - home dispatcher
  - index (foreman dashboard / staff redirect)
  - profile_view
  - change_password_view
  - switch_active_warehouse
  - material_list
  - material_detail
  - load_stages (AJAX)
"""
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from django.core.cache import cache

from warehouse.models import Material, Warehouse, ConstructionStage
from warehouse.tests.base import BaseTestCase


class HomeViewTests(BaseTestCase):
    """home view dispatches by role."""

    def test_staff_redirects_to_manager_dashboard(self):
        self.login_staff()
        resp = self.client.get(reverse('home'))
        self.assertRedirects(resp, reverse('manager_dashboard'), fetch_redirect_response=False)

    def test_foreman_redirects_to_index(self):
        self.login_foreman()
        resp = self.client.get(reverse('home'))
        self.assertRedirects(resp, reverse('index'), fetch_redirect_response=False)

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp['Location'])


class IndexViewTests(BaseTestCase):
    """index (dashboard/) view."""

    def test_staff_redirects_to_manager_dashboard(self):
        self.login_staff()
        resp = self.client.get(reverse('index'))
        self.assertRedirects(resp, reverse('manager_dashboard'), fetch_redirect_response=False)

    def test_foreman_gets_200(self):
        self.login_foreman()
        resp = self.client.get(reverse('index'))
        self.assertEqual(resp.status_code, 200)

    def test_foreman_uses_session_active_warehouse(self):
        self.login_foreman()
        session = self.client.session
        session['active_warehouse_id'] = self.wh_main.pk
        session.save()
        resp = self.client.get(reverse('index'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['active_warehouse'], self.wh_main)

    def test_foreman_no_warehouses_renders_without_crash(self):
        """other_user has no warehouses — should not crash."""
        self.client.force_login(self.other_user)
        resp = self.client.get(reverse('index'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context.get('items_count', 0), 0)

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('index'))
        self.assertEqual(resp.status_code, 302)


class ProfileViewTests(BaseTestCase):
    """profile_view GET/POST."""

    def test_get_returns_200(self):
        self.login_foreman()
        resp = self.client.get(reverse('profile'))
        self.assertEqual(resp.status_code, 200)

    def test_post_valid_updates_user_and_redirects(self):
        self.login_foreman()
        resp = self.client.post(reverse('profile'), {
            'first_name': 'Ivan',
            'last_name': 'Shevchenko',
            'email': 'ivan@test.com',
        })
        self.assertRedirects(resp, reverse('profile'), fetch_redirect_response=False)
        self.foreman_user.refresh_from_db()
        self.assertEqual(self.foreman_user.first_name, 'Ivan')

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('profile'))
        self.assertEqual(resp.status_code, 302)


class ChangePasswordViewTests(BaseTestCase):
    """change_password_view GET/POST."""

    def test_get_returns_200(self):
        self.login_foreman()
        resp = self.client.get(reverse('change_password'))
        self.assertEqual(resp.status_code, 200)

    def test_post_valid_changes_password(self):
        self.login_foreman()
        resp = self.client.post(reverse('change_password'), {
            'old_password': 'pass',
            'new_password1': 'newStrongP@ssw0rd!',
            'new_password2': 'newStrongP@ssw0rd!',
        })
        # On success renders password_change_done.html (200)
        self.assertEqual(resp.status_code, 200)
        # Verify the password was actually changed
        self.foreman_user.refresh_from_db()
        self.assertTrue(self.foreman_user.check_password('newStrongP@ssw0rd!'))

    def test_post_wrong_old_password_shows_errors(self):
        self.login_foreman()
        resp = self.client.post(reverse('change_password'), {
            'old_password': 'wrongpass',
            'new_password1': 'newStrongP@ss1!',
            'new_password2': 'newStrongP@ss1!',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context['form'].is_valid())


class SwitchActiveWarehouseTests(BaseTestCase):
    """switch_active_warehouse session management and security."""

    def test_allowed_warehouse_sets_session(self):
        self.login_foreman()
        resp = self.client.get(
            reverse('switch_active_warehouse', args=[self.wh_main.pk])
        )
        # Should redirect (to referer or index)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.session.get('active_warehouse_id'), self.wh_main.pk)

    def test_forbidden_warehouse_does_not_set_session(self):
        self.login_foreman()
        old_value = self.client.session.get('active_warehouse_id')
        self.client.get(
            reverse('switch_active_warehouse', args=[self.wh_other.pk])
        )
        self.assertEqual(self.client.session.get('active_warehouse_id'), old_value)

    def test_open_redirect_protection(self):
        """External referer should NOT be followed."""
        self.login_foreman()
        resp = self.client.get(
            reverse('switch_active_warehouse', args=[self.wh_main.pk]),
            HTTP_REFERER='http://evil.com/steal'
        )
        # Should redirect to 'index', not to evil.com
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn('evil.com', resp['Location'])

    def test_safe_referer_is_followed(self):
        self.login_foreman()
        safe_url = 'http://testserver' + reverse('index')
        resp = self.client.get(
            reverse('switch_active_warehouse', args=[self.wh_main.pk]),
            HTTP_REFERER=safe_url
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('index'), resp['Location'])


class MaterialListViewTests(BaseTestCase):
    """material_list: listing and search."""

    def test_returns_200(self):
        self.login_foreman()
        resp = self.client.get(reverse('material_list'))
        self.assertEqual(resp.status_code, 200)

    def test_search_filters_by_name(self):
        self.login_foreman()
        resp = self.client.get(reverse('material_list'), {'q': 'Cement'})
        self.assertEqual(resp.status_code, 200)
        materials = list(resp.context['materials'])
        names = [m.name for m in materials]
        self.assertIn('Cement', names)
        self.assertNotIn('Brick', names)

    def test_pagination_with_many_materials(self):
        self.login_foreman()
        # Create 25 extra materials to force pagination
        for i in range(25):
            Material.objects.create(name=f'TestMat{i:02d}', unit='pcs')
        resp = self.client.get(reverse('material_list'))
        self.assertEqual(resp.status_code, 200)
        # Page 2 should exist
        resp2 = self.client.get(reverse('material_list'), {'page': 2})
        self.assertEqual(resp2.status_code, 200)

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('material_list'))
        self.assertEqual(resp.status_code, 302)


class MaterialDetailViewTests(BaseTestCase):
    """material_detail view."""

    def test_returns_200_for_valid_material(self):
        self.login_foreman()
        resp = self.client.get(reverse('material_detail', args=[self.mat_cement.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_404_for_nonexistent_material(self):
        self.login_foreman()
        resp = self.client.get(reverse('material_detail', args=[99999]))
        self.assertEqual(resp.status_code, 404)

    def test_anonymous_redirects_to_login(self):
        resp = self.client.get(reverse('material_detail', args=[self.mat_cement.pk]))
        self.assertEqual(resp.status_code, 302)


class LoadStagesAjaxTests(BaseTestCase):
    """load_stages AJAX endpoint."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.url = reverse('ajax_load_stages')
        # Create a stage on wh_main (which foreman_user has access to)
        self.stage = ConstructionStage.objects.create(
            name='Foundation', warehouse=self.wh_main
        )

    def test_returns_stages_for_allowed_warehouse(self):
        self.login_foreman()
        resp = self.client.get(self.url, {'warehouse_id': self.wh_main.pk})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(any(s['id'] == self.stage.id for s in data))

    def test_returns_empty_for_forbidden_warehouse(self):
        self.login_foreman()
        resp = self.client.get(self.url, {'warehouse_id': self.wh_other.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_returns_empty_without_warehouse_id(self):
        self.login_foreman()
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_requires_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
