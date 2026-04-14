"""
Tests for warehouse/services/inventory.py:
  - to_decimal()
  - assert_stock_available()
  - InvalidPriceError
"""
from decimal import Decimal
from django.test import TestCase

from warehouse.services.inventory import (
    to_decimal, assert_stock_available,
    InvalidPriceError, InvalidQuantityError, InsufficientStockError,
    create_incoming,
)
from warehouse.tests.base import BaseTestCase


class ToDecimalTests(TestCase):
    """Tests for to_decimal() helper."""

    def test_int_to_decimal(self):
        self.assertEqual(to_decimal(5), Decimal('5.000'))

    def test_float_rounded_to_3_places(self):
        self.assertEqual(to_decimal(1.2345), Decimal('1.235'))

    def test_float_rounded_up(self):
        self.assertEqual(to_decimal(1.2346), Decimal('1.235'))

    def test_string_input(self):
        self.assertEqual(to_decimal('3.14159'), Decimal('3.142'))

    def test_none_returns_zero(self):
        self.assertEqual(to_decimal(None), Decimal('0'))

    def test_invalid_string_returns_zero(self):
        self.assertEqual(to_decimal('abc'), Decimal('0'))

    def test_places_2(self):
        self.assertEqual(to_decimal(3.14159, places=2), Decimal('3.14'))

    def test_already_decimal_passthrough(self):
        self.assertEqual(to_decimal(Decimal('5.000')), Decimal('5.000'))

    def test_zero_input(self):
        self.assertEqual(to_decimal(0), Decimal('0.000'))

    def test_large_number(self):
        result = to_decimal(1234567.89)
        self.assertEqual(result, Decimal('1234567.890'))


class AssertStockAvailableTests(BaseTestCase):
    """Tests for assert_stock_available()."""

    def test_passes_when_stock_sufficient(self):
        self.add_stock(qty=10)
        # Should not raise
        assert_stock_available(self.wh_main, self.mat_cement, Decimal('5.000'))

    def test_passes_when_exactly_equal(self):
        self.add_stock(qty=10)
        # Requesting exactly what's available should pass
        assert_stock_available(self.wh_main, self.mat_cement, Decimal('10.000'))

    def test_raises_when_insufficient(self):
        self.add_stock(qty=5)
        with self.assertRaises(InsufficientStockError):
            assert_stock_available(self.wh_main, self.mat_cement, Decimal('6.000'))

    def test_raises_on_zero_stock(self):
        with self.assertRaises(InsufficientStockError):
            assert_stock_available(self.wh_main, self.mat_cement, Decimal('1.000'))

    def test_zero_requested_does_not_raise(self):
        """allow_zero=True by default, so requesting 0 passes."""
        assert_stock_available(self.wh_main, self.mat_cement, Decimal('0.000'))

    def test_error_has_correct_fields(self):
        self.add_stock(qty=3)
        try:
            assert_stock_available(self.wh_main, self.mat_cement, Decimal('5.000'))
            self.fail("Expected InsufficientStockError")
        except InsufficientStockError as e:
            self.assertEqual(e.warehouse, self.wh_main)
            self.assertEqual(e.material, self.mat_cement)
            self.assertEqual(e.requested_qty, Decimal('5.000'))
            self.assertEqual(e.available_qty, Decimal('3.000'))


class InvalidPriceErrorTests(BaseTestCase):
    """Tests for InvalidPriceError raised by create_incoming()."""

    def test_negative_price_raises(self):
        with self.assertRaises(InvalidPriceError):
            create_incoming(
                self.mat_cement, self.wh_main, 10,
                self.staff_user, price=Decimal('-1.00')
            )

    def test_zero_price_allowed(self):
        # price=0 is fine, just doesn't update avg price
        try:
            create_incoming(
                self.mat_cement, self.wh_main, 10,
                self.staff_user, price=Decimal('0.00')
            )
        except InvalidPriceError:
            self.fail("price=0 should not raise InvalidPriceError")

    def test_positive_price_allowed(self):
        try:
            create_incoming(
                self.mat_cement, self.wh_main, 10,
                self.staff_user, price=Decimal('25.50')
            )
        except InvalidPriceError:
            self.fail("Positive price should not raise InvalidPriceError")

    def test_no_transaction_created_on_negative_price(self):
        from warehouse.models import Transaction
        initial_count = Transaction.objects.count()
        try:
            create_incoming(
                self.mat_cement, self.wh_main, 10,
                self.staff_user, price=Decimal('-5.00')
            )
        except InvalidPriceError:
            pass
        self.assertEqual(Transaction.objects.count(), initial_count)
