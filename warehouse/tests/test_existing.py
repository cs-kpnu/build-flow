"""
Existing 26 tests moved verbatim from warehouse/tests.py.
"""
from django.test import TestCase, Client, RequestFactory
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Sum
from django.urls import reverse
import json
import uuid

from warehouse.models import Warehouse, Material, Transaction, Order, OrderItem, UserProfile, AuditLog
from warehouse.services import inventory
from warehouse.views.reports import period_report
from warehouse.views.utils import enrich_transfers, get_warehouse_balance, work_writeoffs_qs

class WarehouseLogicTests(TestCase):
    def setUp(self):
        # Базові налаштування для всіх тестів
        self.client = Client()
        self.factory = RequestFactory()

        # Створюємо користувача
        self.user = User.objects.create_user(
            username='testadmin',
            email='admin@test.com',
            password='password123'
        )
        self.client.force_login(self.user)

        # Створюємо склади
        self.warehouse_main = Warehouse.objects.create(name='Main Warehouse')
        self.warehouse_site = Warehouse.objects.create(name='Construction Site')

        # Створюємо матеріали (Decimal)
        self.material_cement = Material.objects.create(
            name='Cement',
            unit='kg',
            article='CEM-001',
            current_avg_price=Decimal('50.00')
        )
        self.material_brick = Material.objects.create(
            name='Brick',
            unit='pcs',
            article='BR-001',
            current_avg_price=Decimal('10.00')
        )

    def test_create_incoming_increases_stock(self):
        """1) Перевірка приходу: має збільшуватись залишок."""
        inventory.create_incoming(
            material=self.material_cement,
            warehouse=self.warehouse_main,
            quantity=100, # Decimal(100.000)
            user=self.user,
            price=Decimal('55.00')
        )

        balance = get_warehouse_balance(self.warehouse_main)
        self.assertEqual(balance[self.material_cement], Decimal('100.000'))

        # Перевірка оновлення середньої ціни
        self.material_cement.refresh_from_db()
        self.assertEqual(self.material_cement.current_avg_price, Decimal('55.00'))

    def test_create_writeoff_decreases_stock(self):
        """2) Перевірка списання: має зменшуватись залишок."""
        # Спочатку даємо 100
        inventory.create_incoming(self.material_cement, self.warehouse_main, 100, self.user)

        # Списуємо 30
        inventory.create_writeoff(
            material=self.material_cement,
            warehouse=self.warehouse_main,
            quantity=30,
            user=self.user,
            transaction_type='OUT'
        )

        balance = get_warehouse_balance(self.warehouse_main)
        # 100 - 30 = 70
        self.assertEqual(balance[self.material_cement], Decimal('70.000'))

    def test_transfer_moves_stock_between_warehouses(self):
        """3) Перевірка переміщення: списує з джерела, додає на приймач."""
        # 1. Прихід на головний склад: 50 шт
        inventory.create_incoming(self.material_brick, self.warehouse_main, 50, self.user)

        # 2. Переміщення на об'єкт: 20 шт
        group_id = inventory.create_transfer(
            user=self.user,
            material=self.material_brick,
            source_warehouse=self.warehouse_main,
            target_warehouse=self.warehouse_site,
            quantity=20,
            description="Transfer test"
        )

        self.assertIsInstance(group_id, uuid.UUID)

        # Перевіряємо баланс Main (50 - 20 = 30)
        bal_main = get_warehouse_balance(self.warehouse_main)
        self.assertEqual(bal_main[self.material_brick], Decimal('30.000'))

        # Перевіряємо баланс Site (0 + 20 = 20)
        bal_site = get_warehouse_balance(self.warehouse_site)
        self.assertEqual(bal_site[self.material_brick], Decimal('20.000'))

    def test_transfer_journal_groups_by_transfer_group_id(self):
        """4) Журнал переміщень має групувати записи."""

        # 0. Спочатку додаємо залишки на склад, щоб можна було робити трансфер
        inventory.create_incoming(self.material_cement, self.warehouse_main, 100, self.user)
        inventory.create_incoming(self.material_brick, self.warehouse_main, 100, self.user)

        # 1. Трансфер цементу (група 1)
        inventory.create_transfer(
            user=self.user,
            material=self.material_cement,
            source_warehouse=self.warehouse_main,
            target_warehouse=self.warehouse_site,
            quantity=10,
            description="Transfer Cement"
        )

        # 2. Трансфер цегли (група 2)
        inventory.create_transfer(
            user=self.user,
            material=self.material_brick,
            source_warehouse=self.warehouse_main,
            target_warehouse=self.warehouse_site,
            quantity=5,
            description="Transfer Brick"
        )

        # Отримуємо всі транзакції з group_id
        qs = Transaction.objects.filter(transfer_group_id__isnull=False)

        # Використовуємо утиліту для групування
        journal = enrich_transfers(qs)

        # Має бути 2 записи в журналі (а не 4 транзакції)
        self.assertEqual(len(journal), 2)

        # Перевіряємо вміст першого (останнього по даті) - це Brick
        entry = journal[0]
        self.assertEqual(entry['material'], 'Brick')
        self.assertEqual(entry['quantity'], Decimal('5.000'))

    def test_process_order_receipt_completes_order(self):
        """5) Прийом по заявці завершує її та створює транзакцію."""
        order = Order.objects.create(
            warehouse=self.warehouse_main,
            status='purchasing',
            created_by=self.user
        )
        item = OrderItem.objects.create(
            order=order,
            material=self.material_cement,
            quantity=Decimal('50.000'),
            supplier_price=Decimal('52.00')
        )

        # Імітуємо прийом
        items_data = {item.id: 50}
        inventory.process_order_receipt(order, items_data, self.user)

        # Перевіряємо статус заявки
        order.refresh_from_db()
        self.assertEqual(order.status, 'completed')

        # Перевіряємо створення транзакції
        tx_exists = Transaction.objects.filter(order=order, transaction_type='IN').exists()
        self.assertTrue(tx_exists)

        # Перевіряємо баланс
        bal = get_warehouse_balance(self.warehouse_main)
        self.assertEqual(bal[self.material_cement], Decimal('50.000'))

    def test_period_report_calculation(self):
        """6) Перевірка розрахунку оборотної відомості."""
        # 1. Початковий залишок (вчора): 100
        yesterday = timezone.now().date() - timezone.timedelta(days=1)
        inventory.create_incoming(self.material_cement, self.warehouse_main, 100, self.user, date=yesterday)

        # 2. Рух сьогодні: +50, -20
        today = timezone.now().date()
        inventory.create_incoming(self.material_cement, self.warehouse_main, 50, self.user, date=today)

        # Використовуємо transaction_type явно
        inventory.create_writeoff(
            material=self.material_cement,
            warehouse=self.warehouse_main,
            quantity=20,
            user=self.user,
            transaction_type='OUT',
            date=today
        )

        # Баланс на кінець
        final_bal = get_warehouse_balance(self.warehouse_main)
        # 100 + 50 - 20 = 130
        self.assertEqual(final_bal[self.material_cement], Decimal('130.000'))

    def test_decimal_precision(self):
        """7) Перевірка точності Decimal (3 знаки)."""
        from warehouse.services.inventory import InvalidQuantityError

        # Спроба додати дробове число (float)
        inventory.create_incoming(self.material_cement, self.warehouse_main, 10.12345, self.user)

        balance = get_warehouse_balance(self.warehouse_main)
        # Має округлитись до 3 знаків: 10.123
        self.assertEqual(balance[self.material_cement], Decimal('10.123'))

        # Кількість 0.0004 округлюється до 0.000 - має викликати помилку
        with self.assertRaises(InvalidQuantityError):
            inventory.create_incoming(self.material_cement, self.warehouse_main, 0.0004, self.user)

        balance = get_warehouse_balance(self.warehouse_main)
        self.assertEqual(balance[self.material_cement], Decimal('10.123'))  # Без змін

        # Додаємо щось, що округлиться вгору (0.0006 -> 0.001)
        inventory.create_incoming(self.material_cement, self.warehouse_main, 0.0006, self.user)
        balance = get_warehouse_balance(self.warehouse_main)
        self.assertEqual(balance[self.material_cement], Decimal('10.124'))


class AjaxWarehouseStockTests(TestCase):
    """
    Тести для AJAX endpoint отримання залишків (ajax_warehouse_stock).
    """
    def setUp(self):
        self.client = Client()

        # 1. Створюємо звичайного користувача (не адмін)
        self.user = User.objects.create_user(username='foreman', password='password')
        # Створюємо профіль, якщо він не створюється сигналом (або щоб переконатись)
        if not hasattr(self.user, 'profile'):
            self.profile = UserProfile.objects.create(user=self.user)
        else:
            self.profile = self.user.profile

        # 2. Створюємо склади
        self.wh_allowed = Warehouse.objects.create(name='Allowed Warehouse')
        self.wh_forbidden = Warehouse.objects.create(name='Forbidden Warehouse')

        # Надаємо доступ тільки до одного складу через M2M поле warehouses
        self.profile.warehouses.add(self.wh_allowed)

        # 3. Матеріали
        self.mat_a = Material.objects.create(name='Alpha Block', unit='pcs', current_avg_price=Decimal('10.00'))
        self.mat_z = Material.objects.create(name='Zebra Cement', unit='kg', current_avg_price=Decimal('5.00'))

        # 4. Наповнюємо склад (10.5 шт Alpha, 20.000 кг Zebra)
        inventory.create_incoming(self.mat_a, self.wh_allowed, 10.5, self.user)
        inventory.create_incoming(self.mat_z, self.wh_allowed, 20, self.user)

        # 5. URLs
        # Canonical: ajax/warehouse/<id>/stock/
        self.url_allowed = reverse('ajax_warehouse_stock', args=[self.wh_allowed.id])
        self.url_forbidden = reverse('ajax_warehouse_stock', args=[self.wh_forbidden.id])
        # Legacy: ajax/warehouse-stock/
        self.url_legacy = reverse('ajax_warehouse_stock_legacy')

    def test_auth_required_canonical(self):
        """1) Неавтентифікований запит на canonical URL має редіректити (302)."""
        response = self.client.get(self.url_allowed)
        self.assertEqual(response.status_code, 302)

    def test_access_control_forbidden_canonical(self):
        """2) Доступ до забороненого складу через canonical URL -> 404."""
        self.client.force_login(self.user)
        response = self.client.get(self.url_forbidden)
        # enforce_warehouse_access_or_404 викликає Http404, тому очікуємо 404
        self.assertEqual(response.status_code, 404)

    def test_access_control_allowed_canonical(self):
        """3) Успішний доступ до дозволеного складу через canonical URL -> 200."""
        self.client.force_login(self.user)
        response = self.client.get(self.url_allowed)
        self.assertEqual(response.status_code, 200)

    def test_json_structure_canonical(self):
        """4) Перевірка структури JSON та типів даних (canonical)."""
        self.client.force_login(self.user)
        response = self.client.get(self.url_allowed)
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data['warehouse_id'], self.wh_allowed.id)
        self.assertIn('items', data)

        items = data['items']
        self.assertEqual(len(items), 2)

        # Перевірка конкретного матеріалу
        alpha = next(i for i in items if i['material_id'] == self.mat_a.id)
        self.assertEqual(alpha['name'], 'Alpha Block')

        # 🔥 Перевіряємо qty через Decimal, бо це рядок
        self.assertEqual(Decimal(alpha['qty']), Decimal('10.500'))
        self.assertEqual(alpha['unit'], 'pcs')

    def test_sorting_canonical(self):
        """5) Перевірка сортування матеріалів за назвою (canonical)."""
        self.client.force_login(self.user)
        response = self.client.get(self.url_allowed)
        items = response.json()['items']

        # Alpha (A) < Zebra (Z)
        self.assertEqual(items[0]['name'], 'Alpha Block')
        self.assertEqual(items[1]['name'], 'Zebra Cement')

    def test_missing_warehouse_id_legacy(self):
        """6) Legacy URL без параметра warehouse_id -> 400."""
        self.client.force_login(self.user)
        response = self.client.get(self.url_legacy)
        self.assertEqual(response.status_code, 400)

    def test_invalid_warehouse_id_legacy(self):
        """7) Legacy URL з некоректним warehouse_id -> 404."""
        self.client.force_login(self.user)
        response = self.client.get(self.url_legacy, {'warehouse_id': 'abc'})
        # View повертає 404 для невалідного ID у try-except блоці
        self.assertEqual(response.status_code, 404)

    def test_nonexistent_warehouse_id_canonical(self):
        """8) Canonical URL з неіснуючим warehouse_id -> 404."""
        self.client.force_login(self.user)
        url_404 = reverse('ajax_warehouse_stock', args=[99999])
        response = self.client.get(url_404)
        self.assertEqual(response.status_code, 404)


class StockValidationTests(TestCase):
    """
    Регресійні тести для server-side stock validation (Етап 6).
    Перевіряємо, що неможливо списати або перемістити більше, ніж є на складі.
    """
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='stocktester', password='password')
        self.wh_main = Warehouse.objects.create(name='Main Stock')
        self.wh_dest = Warehouse.objects.create(name='Dest Stock')
        # FIX: Використання Decimal для ціни
        self.mat_sand = Material.objects.create(name='Sand', unit='kg', current_avg_price=Decimal('10.00'))

    def test_writeoff_cannot_go_negative(self):
        """1) Списання (OUT) більше, ніж є -> InsufficientStockError."""
        # IN 5.000
        inventory.create_incoming(self.mat_sand, self.wh_main, 5.000, self.user)

        # Спроба списати 6.000
        with self.assertRaises(inventory.InsufficientStockError):
            inventory.create_writeoff(
                material=self.mat_sand,
                warehouse=self.wh_main,
                quantity=6.000,
                user=self.user,
                transaction_type='OUT'
            )

        # Перевіряємо, що OUT транзакція не створилась
        out_tx_count = Transaction.objects.filter(transaction_type='OUT', warehouse=self.wh_main).count()
        self.assertEqual(out_tx_count, 0)

        # Баланс має залишитись 5.000
        bal = get_warehouse_balance(self.wh_main)
        self.assertEqual(bal[self.mat_sand], Decimal('5.000'))

    def test_transfer_cannot_go_negative(self):
        """2) Переміщення більше, ніж є -> InsufficientStockError."""
        # IN 3.000
        inventory.create_incoming(self.mat_sand, self.wh_main, 3.000, self.user)

        # Спроба перемістити 4.000
        with self.assertRaises(inventory.InsufficientStockError):
            inventory.create_transfer(
                user=self.user,
                material=self.mat_sand,
                source_warehouse=self.wh_main,
                target_warehouse=self.wh_dest,
                quantity=4.000
            )

        # Перевіряємо, що транзакцій переміщення не створено
        group_tx_count = Transaction.objects.filter(transfer_group_id__isnull=False).count()
        self.assertEqual(group_tx_count, 0)

        # Баланс джерела 3.000, призначення 0
        bal_main = get_warehouse_balance(self.wh_main)
        bal_dest = get_warehouse_balance(self.wh_dest)
        self.assertEqual(bal_main[self.mat_sand], Decimal('3.000'))
        self.assertEqual(bal_dest.get(self.mat_sand, 0), Decimal('0'))

    def test_valid_writeoff_succeeds(self):
        """3) Валідне списання в межах залишку проходить успішно."""
        # IN 5.000
        inventory.create_incoming(self.mat_sand, self.wh_main, 5.000, self.user)

        # Списання 2.500
        inventory.create_writeoff(
            material=self.mat_sand,
            warehouse=self.wh_main,
            quantity=2.500,
            user=self.user,
            transaction_type='OUT'
        )

        # Залишок має бути 2.500
        bal = get_warehouse_balance(self.wh_main)
        self.assertEqual(bal[self.mat_sand], Decimal('2.500'))

    def test_valid_transfer_succeeds(self):
        """4) Валідне переміщення проходить успішно."""
        # IN 5.000
        inventory.create_incoming(self.mat_sand, self.wh_main, 5.000, self.user)

        # Переміщення 2.000
        group_id = inventory.create_transfer(
            user=self.user,
            material=self.mat_sand,
            source_warehouse=self.wh_main,
            target_warehouse=self.wh_dest,
            quantity=2.000
        )

        self.assertIsNotNone(group_id)

        # Перевірка балансів: Main=3.000, Dest=2.000
        bal_main = get_warehouse_balance(self.wh_main)
        bal_dest = get_warehouse_balance(self.wh_dest)

        self.assertEqual(bal_main[self.mat_sand], Decimal('3.000'))
        self.assertEqual(bal_dest[self.mat_sand], Decimal('2.000'))

        # Перевірка наявності записів з group_id
        txs = Transaction.objects.filter(transfer_group_id=group_id)
        self.assertEqual(txs.count(), 2)


class RegressionCriticalFlowsTests(TestCase):
    """
    Етап 7: Регресійні тести критичних сценаріїв.
    """
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='regress_user', password='password')

        # FIX: Безпечне створення або отримання профілю
        if hasattr(self.user, 'profile'):
            self.profile = self.user.profile
        else:
            self.profile = UserProfile.objects.create(user=self.user)

        self.wh_1 = Warehouse.objects.create(name='Warehouse 1')
        self.wh_2 = Warehouse.objects.create(name='Warehouse 2')

        # Grant access to WH 1 only
        self.profile.warehouses.add(self.wh_1)

        self.mat = Material.objects.create(name='Test Mat', unit='kg', current_avg_price=Decimal('10.00'))

    def test_transfer_not_counted_as_spent_in_reports(self):
        """
        1) Перевірка, що транзакції переміщення не входять у витрати (work_writeoffs_qs).
        """
        # IN
        inventory.create_incoming(self.mat, self.wh_1, 100, self.user)
        # Transfer 10
        inventory.create_transfer(self.user, self.mat, self.wh_1, self.wh_2, 10)

        # Отримуємо всі транзакції
        qs = Transaction.objects.all()
        # Фільтруємо через work_writeoffs_qs (тільки витрати на роботи)
        filtered = work_writeoffs_qs(qs)

        # У filtered НЕ має бути транзакції transfer OUT
        count = filtered.count()
        self.assertEqual(count, 0)

        # Створимо реальне списання
        inventory.create_writeoff(self.mat, self.wh_1, 5, self.user, transaction_type='OUT')

        filtered = work_writeoffs_qs(Transaction.objects.all())
        total_qty = filtered.aggregate(s=Sum('quantity'))['s']
        # Має бути тільки 5 (списання), а не 15 (списання + трансфер)
        self.assertEqual(total_qty, Decimal('5.000'))

    def test_ajax_stock_respects_warehouse_access(self):
        """
        2) Перевірка доступу до AJAX залишків та ізоляції даних.
        """
        self.client.force_login(self.user)

        # Додаємо залишки
        inventory.create_incoming(self.mat, self.wh_1, 10, self.user)
        inventory.create_incoming(self.mat, self.wh_2, 20, self.user)

        # Запит до дозволеного складу
        url_ok = reverse('ajax_warehouse_stock', args=[self.wh_1.id])
        resp_ok = self.client.get(url_ok)
        self.assertEqual(resp_ok.status_code, 200)
        data = resp_ok.json()

        # Перевіряємо кількість (має бути 10, а не 20 чи 30)
        item = next(i for i in data['items'] if i['material_id'] == self.mat.id)
        self.assertEqual(Decimal(item['qty']), Decimal('10.000'))

        # Запит до забороненого складу -> 404
        url_fail = reverse('ajax_warehouse_stock', args=[self.wh_2.id])
        resp_fail = self.client.get(url_fail)
        self.assertEqual(resp_fail.status_code, 404)

    def test_reports_respect_warehouse_access(self):
        """
        3) Звіти повинні бути доступні тільки для staff (після рефакторингу @staff_required).
        """
        # Reports are now @staff_required — elevate user to staff for this test
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

        inventory.create_incoming(self.mat, self.wh_1, 10, self.user)
        inventory.create_incoming(self.mat, self.wh_2, 20, self.user)

        # Stock Balance Report should return 200 for staff
        url = reverse('stock_balance_report')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode('utf-8')
        # Warehouse 1 data must appear
        self.assertIn('Warehouse 1', content)

    def test_insufficient_stock_no_side_effects(self):
        """
        4) Помилка списання не повинна залишати "сміття" в БД.
        """
        inventory.create_incoming(self.mat, self.wh_1, 10, self.user)

        # Спроба списати більше, ніж є
        with self.assertRaises(inventory.InsufficientStockError):
            inventory.create_writeoff(self.mat, self.wh_1, 20, self.user)

        # Транзакцій OUT не має бути
        self.assertEqual(Transaction.objects.filter(transaction_type='OUT').count(), 0)

        # Спроба перемістити більше, ніж є
        with self.assertRaises(inventory.InsufficientStockError):
            inventory.create_transfer(self.user, self.mat, self.wh_1, self.wh_2, 20)

        # Групових транзакцій не має бути
        self.assertEqual(Transaction.objects.filter(transfer_group_id__isnull=False).count(), 0)

    def test_decimal_money_math_stable(self):
        """
        5) Перевірка математики Decimal (точність, округлення).
        """
        # Створюємо прихід з дробовою кількістю та ціною
        # 1.235 * 10.99 = 13.57265 -> 13.57 (ROUND_HALF_UP)
        inventory.create_incoming(self.mat, self.wh_1, Decimal('1.235'), self.user, price=Decimal('10.99'))

        self.mat.refresh_from_db()
        # Середня ціна оновлюється
        self.assertEqual(self.mat.current_avg_price, Decimal('10.99'))

        # Перевіряємо збережену вартість (розрахунково)
        tx = Transaction.objects.first()
        val = (tx.quantity * tx.price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.assertEqual(val, Decimal('13.57'))

    def test_empty_reports_do_not_crash(self):
        """
        6) Порожні звіти повинні відкриватися без помилок (200 OK).
        Reports are @staff_required, so staff login is required.
        """
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

        reports_urls = [
            reverse('stock_balance_report'),
            reverse('period_report'),
            reverse('writeoff_report'),
        ]

        for url in reports_urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, f"Failed at {url}")

    def test_audit_log_does_not_break_actions(self):
        """
        7) Логування аудиту не повинно ламати основні дії.
        """
        self.client.force_login(self.user)

        # Поповнюємо склад, щоб вистачило для списання (якщо логіка перевіряє залишки)
        inventory.create_incoming(self.mat, self.wh_1, 100, self.user)

        # Використовуємо view add_transaction, яка викликає log_audit
        url = reverse('add_transaction')
        data = {
            'transaction_type': 'IN',
            'warehouse': self.wh_1.id,
            'material': self.mat.id,
            'quantity': '5.000',
            'description': 'Audit Test'
        }

        resp = self.client.post(url, data)
        # Успішне створення -> редірект
        self.assertEqual(resp.status_code, 302)

        # Перевіряємо, що транзакцію створено
        tx_exists = Transaction.objects.filter(description='Audit Test').exists()
        self.assertTrue(tx_exists, "Transaction should be created")

        # Перевіряємо, що запис в AuditLog створено (якщо модель доступна)
        if AuditLog._meta.db_table:
            log_exists = AuditLog.objects.filter(action_type='CREATE', user=self.user).exists()
            self.assertTrue(log_exists, "Audit log entry not found")
