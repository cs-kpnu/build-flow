"""
Shared BaseTestCase with common fixtures for all warehouse tests.

Signal note: post_save on User auto-creates UserProfile.
Never call UserProfile.objects.create(user=...) for users created here — IntegrityError.
Access via user.profile.
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User, Group
from decimal import Decimal

from warehouse.models import (
    Warehouse, Material, Order, OrderItem, UserProfile,
)
from warehouse.services import inventory


class BaseTestCase(TestCase):
    """
    Shared fixtures for all warehouse tests.
    Uses setUpTestData (class-level, one DB setup per TestCase class).
    setUp resets the client per test instance.
    """

    @classmethod
    def setUpTestData(cls):
        # ── Users ──────────────────────────────────────────────────────────────
        cls.staff_user = User.objects.create_user(
            username='manager', password='pass', is_staff=True
        )
        cls.superuser = User.objects.create_superuser(
            username='admin', password='pass', email='admin@test.com'
        )
        cls.foreman_user = User.objects.create_user(
            username='foreman', password='pass'
        )
        cls.other_user = User.objects.create_user(
            username='other', password='pass'
        )

        # ── Groups ─────────────────────────────────────────────────────────────
        cls.foreman_group = Group.objects.create(name='Foreman')
        cls.foreman_user.groups.add(cls.foreman_group)

        # ── Warehouses ─────────────────────────────────────────────────────────
        cls.wh_main = Warehouse.objects.create(
            name='Main Warehouse', budget_limit=Decimal('100000.00')
        )
        cls.wh_site = Warehouse.objects.create(
            name='Site A', budget_limit=Decimal('50000.00')
        )
        cls.wh_other = Warehouse.objects.create(name='Other Warehouse')

        # ── Warehouse access (profile auto-created by signal) ──────────────────
        cls.foreman_user.profile.warehouses.add(cls.wh_main)
        # other_user and staff_user get NO explicit warehouse assignments
        # (staff sees all, other_user sees none)

        # ── Materials ──────────────────────────────────────────────────────────
        cls.mat_cement = Material.objects.create(
            name='Cement', unit='kg', article='CEM-001',
            current_avg_price=Decimal('50.00')
        )
        cls.mat_brick = Material.objects.create(
            name='Brick', unit='pcs', article='BR-001',
            current_avg_price=Decimal('10.00')
        )

    def setUp(self):
        self.client = Client()

    # ── Convenience login helpers ──────────────────────────────────────────────
    def login_staff(self):
        self.client.force_login(self.staff_user)

    def login_foreman(self):
        self.client.force_login(self.foreman_user)

    def login_super(self):
        self.client.force_login(self.superuser)

    # ── Data creation helpers ──────────────────────────────────────────────────
    def make_order(self, warehouse=None, status='new', user=None):
        """Create a minimal Order with one OrderItem."""
        order = Order.objects.create(
            warehouse=warehouse or self.wh_main,
            status=status,
            created_by=user or self.foreman_user,
        )
        OrderItem.objects.create(
            order=order,
            material=self.mat_cement,
            quantity=Decimal('10.000'),
            supplier_price=Decimal('52.00'),
        )
        return order

    def add_stock(self, material=None, warehouse=None, qty=100, user=None, price=None):
        """Put stock into a warehouse via create_incoming."""
        return inventory.create_incoming(
            material or self.mat_cement,
            warehouse or self.wh_main,
            qty,
            user or self.staff_user,
            price=price,
        )
