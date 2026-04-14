"""
Tests for warehouse/forms.py:
  - TransactionForm validation (stock check, file validation)
  - OrderForm IDOR protection (warehouse access)
  - ProfileUpdateForm image validation
"""
from decimal import Decimal
from io import BytesIO

from django.test import TestCase
from django.core.files.uploadedfile import InMemoryUploadedFile, SimpleUploadedFile

from warehouse.forms import TransactionForm, OrderForm, ProfileUpdateForm
from warehouse.models import Transaction
from warehouse.services import inventory
from warehouse.tests.base import BaseTestCase


# ---------------------------------------------------------------------------
# Helper: create a real in-memory PNG image file
# ---------------------------------------------------------------------------

def make_image_file(name='test.png', size_kb=10):
    """Returns an InMemoryUploadedFile with a real PNG."""
    from PIL import Image
    img = Image.new('RGB', (100, 100), color='red')
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    file_size = buf.getbuffer().nbytes
    return InMemoryUploadedFile(buf, 'photo', name, 'image/png', file_size, None)


def make_large_fake_file(name='big.png', size_mb=11):
    """Returns a SimpleUploadedFile that exceeds MAX_UPLOAD_SIZE."""
    data = b'x' * (size_mb * 1024 * 1024)
    return SimpleUploadedFile(name, data, content_type='image/png')


# ---------------------------------------------------------------------------
# TransactionForm
# ---------------------------------------------------------------------------

class TransactionFormValidationTests(BaseTestCase):
    """Tests for TransactionForm stock check and file validation."""

    def setUp(self):
        super().setUp()
        # Put 50 units of cement on wh_main
        self.add_stock(qty=50)

    def _build_form_data(self, t_type='IN', qty='10.000', warehouse=None, material=None):
        return {
            'transaction_type': t_type,
            'warehouse': (warehouse or self.wh_main).pk,
            'material': (material or self.mat_cement).pk,
            'quantity': qty,
            'description': '',
        }

    def test_valid_in_form_passes(self):
        data = self._build_form_data(t_type='IN', qty='10.000')
        form = TransactionForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_out_within_stock_passes(self):
        data = self._build_form_data(t_type='OUT', qty='20.000')
        form = TransactionForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_out_exceeds_stock_fails(self):
        data = self._build_form_data(t_type='OUT', qty='100.000')
        form = TransactionForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('__all__', form.errors)

    def test_loss_exceeds_stock_fails(self):
        data = self._build_form_data(t_type='LOSS', qty='100.000')
        form = TransactionForm(data=data)
        self.assertFalse(form.is_valid())

    def test_invalid_photo_extension_fails(self):
        data = self._build_form_data()
        bad_file = SimpleUploadedFile('doc.txt', b'hello', content_type='text/plain')
        form = TransactionForm(data=data, files={'photo': bad_file})
        self.assertFalse(form.is_valid())
        self.assertIn('photo', form.errors)

    def test_valid_png_photo_passes(self):
        data = self._build_form_data()
        good_file = make_image_file('photo.png')
        form = TransactionForm(data=data, files={'photo': good_file})
        self.assertTrue(form.is_valid(), form.errors)

    def test_oversized_photo_fails(self):
        data = self._build_form_data()
        big_file = make_large_fake_file('big.png', size_mb=11)
        form = TransactionForm(data=data, files={'photo': big_file})
        self.assertFalse(form.is_valid())
        self.assertIn('photo', form.errors)

    def test_zero_quantity_fails(self):
        data = self._build_form_data(qty='0.000')
        form = TransactionForm(data=data)
        self.assertFalse(form.is_valid())

    def test_negative_quantity_fails(self):
        data = self._build_form_data(qty='-1.000')
        form = TransactionForm(data=data)
        self.assertFalse(form.is_valid())


# ---------------------------------------------------------------------------
# OrderForm IDOR protection
# ---------------------------------------------------------------------------

class OrderFormIDORProtectionTests(BaseTestCase):
    """Tests that foreman cannot select a warehouse they don't have access to."""

    def _build_order_data(self, warehouse):
        return {
            'warehouse': warehouse.pk,
            'priority': 'medium',
            'note': '',
        }

    def test_foreman_cannot_select_unallowed_warehouse(self):
        """foreman_user has no access to wh_other → ValidationError."""
        data = self._build_order_data(self.wh_other)
        form = OrderForm(data=data, user=self.foreman_user)
        self.assertFalse(form.is_valid())
        self.assertIn('warehouse', form.errors)

    def test_foreman_can_select_allowed_warehouse(self):
        """foreman_user is assigned to wh_main → valid."""
        data = self._build_order_data(self.wh_main)
        form = OrderForm(data=data, user=self.foreman_user)
        self.assertTrue(form.is_valid(), form.errors)

    def test_staff_can_select_any_warehouse(self):
        """Staff users have no warehouse restriction."""
        data = self._build_order_data(self.wh_other)
        form = OrderForm(data=data, user=self.staff_user)
        self.assertTrue(form.is_valid(), form.errors)

    def test_forbidden_request_photo_extension(self):
        """Non-allowed doc extension → ValidationError."""
        data = self._build_order_data(self.wh_main)
        bad_file = SimpleUploadedFile('doc.exe', b'MZ', content_type='application/octet-stream')
        form = OrderForm(data=data, files={'request_photo': bad_file}, user=self.foreman_user)
        self.assertFalse(form.is_valid())
        self.assertIn('request_photo', form.errors)

    def test_pdf_rejected_by_imagefield(self):
        """
        request_photo is an ImageField — Django/Pillow rejects PDF bytes even
        though the custom extension check permits 'pdf'.  The field-level error
        wins before our clean_ method is reached.
        """
        data = self._build_order_data(self.wh_main)
        pdf_file = SimpleUploadedFile('invoice.pdf', b'%PDF-1.4 fake', content_type='application/pdf')
        form = OrderForm(data=data, files={'request_photo': pdf_file}, user=self.foreman_user)
        self.assertFalse(form.is_valid())
        self.assertIn('request_photo', form.errors)

    def test_no_user_kwarg_does_not_crash(self):
        """OrderForm without user kwarg should not crash (user=None path)."""
        data = self._build_order_data(self.wh_main)
        form = OrderForm(data=data, user=None)
        # Doesn't raise, result may or may not be valid depending on queryset
        self.assertIsNotNone(form)


# ---------------------------------------------------------------------------
# ProfileUpdateForm image validation
# ---------------------------------------------------------------------------

class ProfileUpdateFormImageValidationTests(BaseTestCase):
    """Tests for ProfileUpdateForm.clean_photo()."""

    def test_valid_png_photo_passes(self):
        good_file = make_image_file('avatar.png')
        form = ProfileUpdateForm(data={}, files={'photo': good_file})
        # Only photo field is provided; phone/position are optional — form should be valid
        self.assertTrue(form.is_valid(), form.errors)

    def test_invalid_extension_fails(self):
        bad_file = SimpleUploadedFile('doc.txt', b'hello', content_type='text/plain')
        form = ProfileUpdateForm(data={}, files={'photo': bad_file})
        self.assertFalse(form.is_valid())
        self.assertIn('photo', form.errors)

    def test_oversized_image_fails(self):
        big_file = make_large_fake_file('big.png', size_mb=11)
        form = ProfileUpdateForm(data={}, files={'photo': big_file})
        self.assertFalse(form.is_valid())
        self.assertIn('photo', form.errors)

    def test_no_photo_is_valid(self):
        """ProfileUpdateForm with no photo is valid (photo is optional)."""
        form = ProfileUpdateForm(data={'phone': '', 'position': ''})
        self.assertTrue(form.is_valid(), form.errors)
