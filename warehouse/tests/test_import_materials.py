"""
Тести для масового імпорту матеріалів через Excel.
"""
import io
import openpyxl
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from warehouse.models import Material, Category

User = get_user_model()


def _make_excel(*rows, headers=None):
    """Допоміжна функція: повертає BytesIO з Excel-файлом."""
    if headers is None:
        headers = ['Назва', 'Артикул', 'Одиниця', 'Категорія',
                   'Характеристики', 'Мін. залишок', 'Середня ціна']
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    buf.name = 'test.xlsx'
    return buf


class ImportMaterialsViewTest(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username='manager', password='pass', is_staff=True
        )
        self.client.force_login(self.staff)
        self.url = reverse('import_materials')

    # ------------------------------------------------------------------
    # Доступ
    # ------------------------------------------------------------------

    def test_get_shows_form(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Імпорт матеріалів')

    def test_non_staff_redirected(self):
        user = User.objects.create_user(username='fore', password='pass')
        self.client.force_login(user)
        resp = self.client.get(self.url)
        self.assertNotEqual(resp.status_code, 200)

    # ------------------------------------------------------------------
    # Шаблон
    # ------------------------------------------------------------------

    def test_template_download(self):
        resp = self.client.get(reverse('import_materials_template'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('spreadsheetml', resp['Content-Type'])
        self.assertIn('.xlsx', resp['Content-Disposition'])

    # ------------------------------------------------------------------
    # Базовий CREATE
    # ------------------------------------------------------------------

    def test_create_new_materials(self):
        xlsx = _make_excel(
            ['Цемент М400', 'CEM-001', 'кг', 'Будматеріали', 'Опис', '100', '5.50'],
            ['Арматура Д10', 'ARM-001', 'т',  'Метал',        '',     '2',   '25000'],
        )
        resp = self.client.post(self.url, {'excel_file': xlsx})
        self.assertEqual(resp.status_code, 200)

        result = resp.context['result']
        self.assertEqual(result['created'], 2)
        self.assertEqual(result['updated'], 0)
        self.assertEqual(result['skipped'], 0)
        self.assertEqual(result['errors'], [])

        m = Material.objects.get(article='CEM-001')
        self.assertEqual(m.name, 'Цемент М400')
        self.assertEqual(m.unit, 'кг')
        self.assertEqual(m.min_limit, Decimal('100.000'))
        self.assertEqual(m.current_avg_price, Decimal('5.50'))
        self.assertEqual(m.category.name, 'Будматеріали')

    # ------------------------------------------------------------------
    # Upsert по артикулу
    # ------------------------------------------------------------------

    def test_update_existing_by_article(self):
        Material.objects.create(
            name='Старий цемент', article='CEM-UPD', unit='шт',
            min_limit=Decimal('0'), current_avg_price=Decimal('1.00'),
        )
        xlsx = _make_excel(
            ['Новий цемент', 'CEM-UPD', 'кг', '', '', '50', '6.00'],
        )
        resp = self.client.post(self.url, {'excel_file': xlsx})
        result = resp.context['result']
        self.assertEqual(result['created'], 0)
        self.assertEqual(result['updated'], 1)

        m = Material.objects.get(article='CEM-UPD')
        self.assertEqual(m.name, 'Новий цемент')
        self.assertEqual(m.unit, 'кг')
        self.assertEqual(m.current_avg_price, Decimal('6.00'))

    # ------------------------------------------------------------------
    # Upsert по назві (без артикулу)
    # ------------------------------------------------------------------

    def test_update_existing_by_name(self):
        Material.objects.create(
            name='Пісок річковий', article=None, unit='т',
            min_limit=Decimal('0'), current_avg_price=Decimal('200'),
        )
        xlsx = _make_excel(
            ['Пісок річковий', '', 'т', 'Сипучі', '', '5', '250'],
        )
        resp = self.client.post(self.url, {'excel_file': xlsx})
        result = resp.context['result']
        self.assertEqual(result['created'], 0)
        self.assertEqual(result['updated'], 1)

        m = Material.objects.get(name='Пісок річковий')
        self.assertEqual(m.category.name, 'Сипучі')
        self.assertEqual(m.current_avg_price, Decimal('250.00'))

    # ------------------------------------------------------------------
    # Порожні рядки пропускаються
    # ------------------------------------------------------------------

    def test_empty_rows_skipped(self):
        xlsx = _make_excel(
            ['Матеріал А', 'MAT-A', 'шт', '', '', '0', '0'],
            ['', '', '', '', '', '', ''],     # порожній
            [None, None, None, None, None, None, None],  # None-рядок
        )
        resp = self.client.post(self.url, {'excel_file': xlsx})
        result = resp.context['result']
        self.assertEqual(result['created'], 1)
        self.assertEqual(result['skipped'], 2)

    # ------------------------------------------------------------------
    # Автоматичне створення категорії
    # ------------------------------------------------------------------

    def test_category_auto_created(self):
        self.assertFalse(Category.objects.filter(name='Нова категорія').exists())
        xlsx = _make_excel(
            ['Матеріал Б', 'MAT-B', 'шт', 'Нова категорія', '', '0', '0'],
        )
        self.client.post(self.url, {'excel_file': xlsx})
        self.assertTrue(Category.objects.filter(name='Нова категорія').exists())

    # ------------------------------------------------------------------
    # Середня ціна не обнуляється
    # ------------------------------------------------------------------

    def test_avg_price_not_overwritten_with_zero(self):
        Material.objects.create(
            name='Дорогий матеріал', article='PRICE-TEST', unit='шт',
            min_limit=Decimal('0'), current_avg_price=Decimal('1000'),
        )
        xlsx = _make_excel(
            ['Дорогий матеріал', 'PRICE-TEST', 'шт', '', '', '0', '0'],
        )
        self.client.post(self.url, {'excel_file': xlsx})
        m = Material.objects.get(article='PRICE-TEST')
        # Ціна 1000 не має бути скинута в 0
        self.assertEqual(m.current_avg_price, Decimal('1000'))

    # ------------------------------------------------------------------
    # Не-Excel файл → помилка
    # ------------------------------------------------------------------

    def test_non_excel_rejected(self):
        fake = io.BytesIO(b'not an excel file')
        fake.name = 'data.txt'
        resp = self.client.post(self.url, {'excel_file': fake})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('result', resp.context or {})

    # ------------------------------------------------------------------
    # Відсутній файл → помилка
    # ------------------------------------------------------------------

    def test_missing_file_rejected(self):
        resp = self.client.post(self.url, {})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('result', resp.context or {})

    # ------------------------------------------------------------------
    # Одиниця за замовчуванням
    # ------------------------------------------------------------------

    def test_default_unit(self):
        xlsx = _make_excel(
            ['Матеріал без одиниці', 'UNIT-DEF', '', '', '', '', ''],
        )
        self.client.post(self.url, {'excel_file': xlsx})
        m = Material.objects.get(article='UNIT-DEF')
        self.assertEqual(m.unit, 'шт')

    # ------------------------------------------------------------------
    # Заголовки без зірочки (шаблонний формат)
    # ------------------------------------------------------------------

    def test_template_headers_recognized(self):
        """Заголовки з шаблону (з зірочками) теж розпізнаються."""
        xlsx = _make_excel(
            ['Матеріал Ш', 'TMPL-001', 'кг', '', '', '10', '3.00'],
            headers=['Назва *', 'Артикул', 'Одиниця (шт за замовч.)',
                     'Категорія', 'Характеристики', 'Мін. залишок', 'Середня ціна (грн)'],
        )
        resp = self.client.post(self.url, {'excel_file': xlsx})
        result = resp.context['result']
        self.assertEqual(result['created'], 1)
        self.assertTrue(Material.objects.filter(article='TMPL-001').exists())
