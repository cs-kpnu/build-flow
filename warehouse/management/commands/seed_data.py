"""
seed_data.py — Повне наповнення бази демо-даними для BudSklad ERP.

Покриває:
  - Користувачі (admin, менеджери, прораби) з профілями
  - Склади / Об'єкти з реалістичними адресами
  - Постачальники з контактами і рейтингами
  - Каталог матеріалів (20+) з характеристиками і цінами постачальників
  - Усі статуси заявок: new → approved → purchasing → transit → completed → rejected
  - Коментарі до заявок (демо чату)
  - Транзакції: IN, OUT, LOSS, TRANSFER — розподілені по 90 днях (для графіків)
  - Переміщення між складами (TRANSFER)
  - Журнал аудиту (AuditLog)
  - Етапи будівництва + ліміти (кошторис)
"""

import random
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group
from django.utils import timezone
from django.db import transaction
from django.conf import settings
from datetime import timedelta

from warehouse.models import (
    Warehouse, Category, Material, Supplier, Transaction,
    UserProfile, Order, OrderItem, OrderComment,
    ConstructionStage, StageLimit, SupplierPrice, AuditLog
)
from warehouse.services import inventory


TODAY = timezone.now().date()


def days_ago(n):
    return TODAY - timedelta(days=n)


class Command(BaseCommand):
    help = 'Наповнює базу повними демо-даними для презентації'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Видалити всі дані перед наповненням (тільки DEBUG)')

    def handle(self, *args, **options):
        if options['reset']:
            if not settings.DEBUG:
                self.stdout.write(self.style.ERROR('RESET дозволено тільки в DEBUG!'))
                return
            self.stdout.write(self.style.WARNING('Видалення даних...'))
            self._clear()
            self.stdout.write(self.style.SUCCESS('Очищено.'))

        self.stdout.write('Генерация демо-даних...')
        try:
            with transaction.atomic():
                self._groups()
                self._users()
                self._warehouses()
                self._suppliers()
                self._catalog()
                self._stages()
                self._initial_stock()
                self._orders()
                self._transfers()
                self._writeoffs()
                self._audit_log()
                self.stdout.write(self.style.SUCCESS('\nГотово!'))
                self.stdout.write("Пароль для всіх: 'demo12345'")
        except Exception as e:
            import traceback
            self.stdout.write(self.style.ERROR(f'Помилка: {e}'))
            traceback.print_exc()

    # ──────────────────────────────────────────────
    # CLEANUP
    # ──────────────────────────────────────────────
    def _clear(self):
        AuditLog.objects.all().delete()
        Transaction.objects.all().delete()
        OrderItem.objects.all().delete()
        OrderComment.objects.all().delete()
        Order.objects.all().delete()
        StageLimit.objects.all().delete()
        ConstructionStage.objects.all().delete()
        SupplierPrice.objects.all().delete()
        Material.objects.all().delete()
        Category.objects.all().delete()
        Supplier.objects.all().delete()
        UserProfile.objects.all().delete()
        User.objects.filter(username__startswith='demo_').delete()
        User.objects.filter(username='admin').delete()

    # ──────────────────────────────────────────────
    # GROUPS
    # ──────────────────────────────────────────────
    def _groups(self):
        self.g_manager, _ = Group.objects.get_or_create(name='Manager')
        self.g_foreman, _  = Group.objects.get_or_create(name='Foreman')

    # ──────────────────────────────────────────────
    # USERS
    # ──────────────────────────────────────────────
    def _users(self):
        self.managers = []
        self.foremen  = []

        # Admin
        admin, created = User.objects.get_or_create(
            username='admin',
            defaults={'email': 'admin@budsklad.ua', 'first_name': 'Олег', 'last_name': 'Коваленко'}
        )
        if created:
            admin.set_password('demo12345')
            admin.is_staff = True
            admin.is_superuser = True
            admin.save()
        self._ensure_profile(admin, 'Головний адміністратор', '+380671234567')
        self.admin = admin
        self.managers.append(admin)

        manager_data = [
            ('demo_manager_1', 'Ірина',  'Петренко', '+380501112233', 'Менеджер з постачання'),
            ('demo_manager_2', 'Василь', 'Мороз',    '+380632223344', 'Старший менеджер'),
        ]
        for uname, fn, ln, phone, pos in manager_data:
            u, created = User.objects.get_or_create(
                username=uname,
                defaults={'email': f'{uname}@budsklad.ua', 'first_name': fn, 'last_name': ln}
            )
            if created:
                u.set_password('demo12345')
                u.is_staff = True
                u.groups.add(self.g_manager)
                u.save()
            self._ensure_profile(u, pos, phone)
            self.managers.append(u)

        foreman_data = [
            ('demo_foreman_1', 'Микола',   'Бондаренко', '+380991234001', 'Виконроб / Бригадир'),
            ('demo_foreman_2', 'Сергій',   'Лисенко',    '+380991234002', 'Виконроб'),
            ('demo_foreman_3', 'Андрій',   'Тимченко',   '+380991234003', 'Виконроб'),
            ('demo_foreman_4', 'Тетяна',   'Іваненко',   '+380991234004', 'Виконроб'),
            ('demo_foreman_5', 'Дмитро',   'Савченко',   '+380991234005', 'Виконроб'),
            ('demo_foreman_6', 'Оксана',   'Ковальська',  '+380991234006', 'Виконроб'),
        ]
        for uname, fn, ln, phone, pos in foreman_data:
            u, created = User.objects.get_or_create(
                username=uname,
                defaults={'email': f'{uname}@budsklad.ua', 'first_name': fn, 'last_name': ln}
            )
            if created:
                u.set_password('demo12345')
                u.is_staff = False
                u.groups.add(self.g_foreman)
                u.save()
            self._ensure_profile(u, pos, phone)
            self.foremen.append(u)

        self.stdout.write(f' > Користувачі: {len(self.managers)} менеджерів, {len(self.foremen)} прорабів.')

    def _ensure_profile(self, user, position, phone):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.position = position
        profile.phone    = phone
        profile.save()

    # ──────────────────────────────────────────────
    # WAREHOUSES
    # ──────────────────────────────────────────────
    def _warehouses(self):
        data = [
            ('Головний Склад',          'вул. Промислова, 10, Київ',         '2000000.00', self.managers[0]),
            ('ЖК "Сонячний"',           'вул. Сонячна, 42, Бровари',         '7500000.00', self.managers[1]),
            ('ТРЦ "Глобус"',            'пр. Перемоги, 1, Київ',             '12000000.00',self.managers[2]),
            ('БЦ "Альфа"',              'вул. Хрещатик, 22, Київ',           '5000000.00', self.managers[1]),
            ('Склад "Захід"',           'Кільцева дорога, 7, Київ',          '500000.00',  self.managers[0]),
        ]
        self.warehouses = []
        for name, addr, budget, resp in data:
            wh, _ = Warehouse.objects.get_or_create(
                name=name,
                defaults={'address': addr, 'budget_limit': Decimal(budget), 'responsible_user': resp}
            )
            self.warehouses.append(wh)

        # Прораби: кожен прив'язаний до 1-2 об'єктів
        foreman_wh_map = [
            (self.foremen[0], [0, 1]),
            (self.foremen[1], [1]),
            (self.foremen[2], [2]),
            (self.foremen[3], [2, 3]),
            (self.foremen[4], [3]),
            (self.foremen[5], [4]),
        ]
        for foreman, idxs in foreman_wh_map:
            foreman.profile.warehouses.set([self.warehouses[i] for i in idxs])

        self.stdout.write(f' > Склади: {len(self.warehouses)} об\'єктів.')

    # ──────────────────────────────────────────────
    # SUPPLIERS
    # ──────────────────────────────────────────────
    def _suppliers(self):
        data = [
            ('Епіцентр К',            'Ігор Дмитренко',  '+380442345678', 'zakup@epicentrk.ua',   'вул. Польова, 5, Київ',       95),
            ('Метінвест',             'Оксана Руденко',  '+380444567890', 'sales@metinvest.ua',   'пр. Науки, 15, Харків',       88),
            ('Ковальська Бетон',      'Петро Ковальський','+380442221133','beton@kovalska.ua',    'вул. Набережна, 3, Київ',     92),
            ('Альянс Буд',            'Марина Степаненко','+380631122334','info@alliancebud.ua', 'вул. Будівельна, 11, Київ',   76),
            ('Техно-Світ',            'Роман Захарченко', '+380501234999','tech@tehnosvit.ua',   'вул. Промислова, 44, Бровари',83),
            ('СтройМет Україна',      'Лариса Яковенко',  '+380671239999','metal@stroymet.ua',   'вул. Залізнична, 2, Дніпро',  91),
        ]
        self.suppliers = []
        for name, cp, phone, email, addr, rating in data:
            s, _ = Supplier.objects.get_or_create(
                name=name,
                defaults={
                    'contact_person': cp, 'phone': phone,
                    'email': email, 'address': addr, 'rating': rating
                }
            )
            self.suppliers.append(s)
        self.stdout.write(f' > Постачальники: {len(self.suppliers)}.')

    # ──────────────────────────────────────────────
    # CATALOG
    # ──────────────────────────────────────────────
    def _catalog(self):
        catalog = {
            'Сипучі матеріали': [
                ('Цемент М-500',         'кг',  'CM-500',   '4.80',   '500.000',
                 'Портландцемент М-500, мішки 50 кг, ДСТУ Б В.2.7-46'),
                ('Пісок річковий',       'т',   'SND-01',   '450.00', '20.000',
                 'Пісок будівельний, фракція 0.1-3 мм, без домішок'),
                ('Щебінь гранітний 5-20','т',   'GRV-20',   '680.00', '15.000',
                 'Щебінь гранітний, фракція 5-20 мм, ДСТУ Б В.2.7-75'),
                ('Керамзит фр. 10-20',   'м3',  'KRZ-10',   '1200.00','5.000',
                 'Керамзит будівельний, фракція 10-20 мм'),
            ],
            'Метал/Арматура': [
                ('Арматура А500С d12',   'т',   'ARM-12',   '28500.00','2.000',
                 'Арматура клас А500С, d=12 мм, L=12 м, ДСТУ 3760'),
                ('Арматура А500С d16',   'т',   'ARM-16',   '27800.00','2.000',
                 'Арматура клас А500С, d=16 мм, L=12 м, ДСТУ 3760'),
                ('Арматура А500С d20',   'т',   'ARM-20',   '27200.00','1.000',
                 'Арматура клас А500С, d=20 мм, L=12 м, ДСТУ 3760'),
                ('Дріт в\'язальний 1.2','кг',  'WR-12',    '65.00',  '50.000',
                 'Дріт в\'язальний термооброблений, d=1.2 мм'),
                ('Балка металева HEA200','м.п.',  'BLK-H200', '850.00', '10.000',
                 'Двотаврова балка HEA 200, Ст3 сп'),
            ],
            'Бетон': [
                ('Бетон В25 М350',       'м3',  'BTN-25',   '3200.00','0.000',
                 'Товарний бетон В25/М350, рухливість П3, ДСТУ Б В.2.7-114'),
                ('Бетон В30 М400',       'м3',  'BTN-30',   '3600.00','0.000',
                 'Товарний бетон В30/М400, рухливість П4, водонепроникний W6'),
            ],
            'Цегла та блоки': [
                ('Цегла рядова М150',    'шт',  'BRK-150',  '9.20',   '500.000',
                 'Цегла керамічна повнотіла М150, розмір 250x120x65 мм'),
                ('Газобетон D500',       'м3',  'GZB-500',  '3100.00','5.000',
                 'Газобетонні блоки D500, B3.5, 600x200x300 мм, ДСТУ Б В.2.7-137'),
                ('Шлакоблок 390x190x188','шт',  'SLG-01',   '28.00',  '100.000',
                 'Шлакоблок стіновий, розмір 390x190x188 мм'),
            ],
            'Покрівля та ізоляція': [
                ('Пінопласт ПСБ-С25 100мм','м2','ISO-100',  '155.00', '20.000',
                 'Пінопласт фасадний ПСБ-С25, 1000x500x100 мм, щільність 25 кг/м3'),
                ('Мінвата Rockwool 100мм', 'm2','RWL-100',  '195.00', '20.000',
                 'Мінеральна вата Rockwool Frontrock, 100 мм, 1000x600'),
                ('Мембрана гідроізоляційна','м2','MBR-01',  '85.00',  '30.000',
                 'Гідроізоляційна мембрана ПВХ, товщина 1.5 мм'),
            ],
            'Спецтехніка та послуги': [
                ('Послуги крана 25т',    'год', 'SRV-CRN',  '2200.00','0.000',
                 'Оренда баштового крана вантажопідйомністю 25т'),
                ('Послуги екскаватора',  'год', 'SRV-EXC',  '1500.00','0.000',
                 'Оренда гусеничного екскаватора, ківш 1 м3'),
                ('Бетононасос',          'год', 'SRV-BNS',  '3500.00','0.000',
                 'Оренда автобетононасоса, стріла 32 м'),
            ],
            'Оздоблення': [
                ('Штукатурка Knauf MP75', 'кг', 'KNF-MP75', '18.50',  '200.000',
                 'Машинна гіпсова штукатурка Knauf MP-75, мішок 30 кг'),
                ('Плитка керамічна 300x300','м2','PLT-300',  '320.00', '10.000',
                 'Керамічна плитка для підлоги, 300x300, клас AB'),
            ],
        }

        self.materials = []
        self.mat_by_category = {}

        for cat_name, items in catalog.items():
            cat, _ = Category.objects.get_or_create(name=cat_name)
            cat_mats = []

            for name, unit, article, price, min_lim, chars in items:
                mat, _ = Material.objects.get_or_create(
                    article=article,
                    defaults={
                        'name': name, 'unit': unit,
                        'category': cat,
                        'current_avg_price': Decimal(price),
                        'min_limit': Decimal(min_lim),
                        'characteristics': chars,
                    }
                )
                self.materials.append(mat)
                cat_mats.append(mat)

                # Ціни: 3-5 постачальників на матеріал
                chosen_suppliers = random.sample(self.suppliers, k=random.randint(3, min(5, len(self.suppliers))))
                for sup in chosen_suppliers:
                    factor = Decimal(str(round(random.uniform(0.88, 1.15), 3)))
                    SupplierPrice.objects.update_or_create(
                        supplier=sup, material=mat,
                        defaults={'price': (Decimal(price) * factor).quantize(Decimal('0.01'))}
                    )

            self.mat_by_category[cat_name] = cat_mats

        self.stdout.write(f' > Каталог: {len(self.materials)} матеріалів.')

    # ──────────────────────────────────────────────
    # STAGES
    # ──────────────────────────────────────────────
    def _stages(self):
        stages_by_wh = {
            'ЖК "Сонячний"': [
                ('Підготовчі роботи',  days_ago(120), days_ago(90),  True),
                ('Фундамент',          days_ago(90),  days_ago(45),  True),
                ('Каркас 1-й поверх',  days_ago(45),  days_ago(10),  False),
                ('Перекриття 1-го пов',days_ago(10),  TODAY+timedelta(20), False),
            ],
            'ТРЦ "Глобус"': [
                ('Демонтаж',           days_ago(80),  days_ago(60),  True),
                ('Котлован',           days_ago(60),  days_ago(30),  True),
                ('Фундаментна плита',  days_ago(30),  TODAY+timedelta(15), False),
                ('Стіни підвалу',      TODAY,         TODAY+timedelta(40), False),
            ],
            'БЦ "Альфа"': [
                ('Проектні роботи',    days_ago(50),  days_ago(20),  True),
                ('Підготовка майданчика',days_ago(20),TODAY+timedelta(10), False),
                ('Пальові роботи',     TODAY+timedelta(5),TODAY+timedelta(35),False),
            ],
        }

        self.all_stages = []
        for wh in self.warehouses:
            wh_stages = stages_by_wh.get(wh.name, [])
            if not wh_stages:
                # Стандартні для складів без специфіки
                wh_stages = [
                    ('Підготовчі роботи', days_ago(60), days_ago(30), True),
                    ('Основні роботи',    days_ago(30), TODAY+timedelta(30), False),
                ]

            for s_name, start, end, completed in wh_stages:
                stage, _ = ConstructionStage.objects.get_or_create(
                    name=s_name, warehouse=wh,
                    defaults={'start_date': start, 'end_date': end, 'completed': completed}
                )
                self.all_stages.append(stage)

                # Ліміти для бетону, металу, блоків
                target_cats = ['Бетон', 'Метал/Арматура', 'Цегла та блоки', 'Сипучі матеріали']
                for cat_name in target_cats:
                    for mat in self.mat_by_category.get(cat_name, [])[:2]:
                        qty = Decimal(str(random.randint(50, 800)))
                        StageLimit.objects.get_or_create(
                            stage=stage, material=mat,
                            defaults={'planned_quantity': qty}
                        )

        self.stdout.write(' > Етапи та ліміти створено.')

    # ──────────────────────────────────────────────
    # INITIAL STOCK  (розподілено по датах для графіків)
    # ──────────────────────────────────────────────
    def _initial_stock(self):
        main = self.warehouses[0]  # Головний склад
        admin = self.admin

        # Завозимо партіями за останні 90 днів → красивий графік приходів
        batches = [
            (days_ago(88), Decimal('3000')),
            (days_ago(70), Decimal('2500')),
            (days_ago(55), Decimal('3500')),
            (days_ago(40), Decimal('2000')),
            (days_ago(25), Decimal('4000')),
            (days_ago(12), Decimal('1500')),
            (days_ago(3),  Decimal('2000')),
        ]

        for mat in self.materials:
            # Кожен матеріал отримує 2-4 приходи в різні дати
            selected_batches = random.sample(batches, k=random.randint(2, 4))
            for batch_date, base_qty in selected_batches:
                qty = (base_qty * Decimal(str(round(random.uniform(0.1, 1.0), 2)))).quantize(Decimal('0.001'))
                if qty < Decimal('1'):
                    qty = Decimal('10.000')
                inventory.create_incoming(
                    material=mat, warehouse=main,
                    quantity=qty, user=admin,
                    price=mat.current_avg_price,
                    description=f'Прихід партії — {mat.name}',
                    date=batch_date,
                )

        # Трохи стоку і на інших складах
        for wh in self.warehouses[1:3]:
            for mat in random.sample(self.materials, k=8):
                qty = Decimal(str(random.randint(50, 300)))
                inventory.create_incoming(
                    material=mat, warehouse=wh,
                    quantity=qty, user=admin,
                    price=mat.current_avg_price,
                    description='Початковий залишок на об\'єкті',
                    date=days_ago(random.randint(30, 80)),
                )

        self.stdout.write(' > Початкові залишки нараховано.')

    # ──────────────────────────────────────────────
    # ORDERS  — кожен статус + коментарі + реалістичні нотатки
    # ──────────────────────────────────────────────
    def _orders(self):
        self.all_orders = []

        # --- 1. ВИКОНАНІ заявки (completed) — створюють стан складу ---
        completed_templates = [
            (self.warehouses[1], self.foremen[0], 'high',
             [('Цемент М-500', 500), ('Пісок річковий', 5), ('Арматура А500С d12', 2)],
             days_ago(60), 'Матеріали для влаштування фундаменту ЖК'),
            (self.warehouses[2], self.foremen[2], 'critical',
             [('Бетон В25 М350', 80), ('Арматура А500С d16', 3)],
             days_ago(50), 'Бетонування перекриття ТРЦ'),
            (self.warehouses[1], self.foremen[1], 'medium',
             [('Газобетон D500', 30), ('Цегла рядова М150', 2000)],
             days_ago(45), 'Кладка стін 2-го поверху'),
            (self.warehouses[3], self.foremen[3], 'high',
             [('Пінопласт ПСБ-С25 100мм', 120), ('Мінвата Rockwool 100мм', 80)],
             days_ago(40), 'Утеплення фасаду БЦ Альфа'),
            (self.warehouses[2], self.foremen[2], 'medium',
             [('Арматура А500С d20', 2), ('Дріт в\'язальний 1.2', 50)],
             days_ago(35), 'Армування монолітних стін'),
            (self.warehouses[1], self.foremen[0], 'high',
             [('Бетон В30 М400', 60), ('Послуги крана 25т', 8)],
             days_ago(28), 'Бетонування плити перекриття 3-го поверху'),
            (self.warehouses[4], self.foremen[5], 'low',
             [('Щебінь гранітний 5-20', 20), ('Пісок річковий', 10)],
             days_ago(22), 'Підготовка під\'їзних шляхів'),
            (self.warehouses[3], self.foremen[3], 'medium',
             [('Штукатурка Knauf MP75', 500), ('Плитка керамічна 300x300', 80)],
             days_ago(15), 'Оздоблювальні роботи офісного блоку'),
        ]
        for wh, creator, prio, items_data, exp_date, note in completed_templates:
            self._create_order_completed(wh, creator, prio, items_data, exp_date, note)

        # --- 2. ВІДХИЛЕНІ заявки ---
        rejected_data = [
            (self.warehouses[1], self.foremen[1], 'low',
             [('Плитка керамічна 300x300', 50)],
             days_ago(30), 'Оздоблення санвузлів (відхилено — не той артикул)'),
            (self.warehouses[2], self.foremen[2], 'medium',
             [('Бетононасос', 5)],
             days_ago(20), 'Оренда бетононасосу — відхилено, немає бюджету'),
        ]
        for wh, creator, prio, items_data, exp_date, note in rejected_data:
            self._create_order_rejected(wh, creator, prio, items_data, exp_date, note)

        # --- 3. В ДОРОЗІ (transit) ---
        transit_data = [
            (self.warehouses[1], self.foremen[0], 'critical',
             [('Арматура А500С d16', 5), ('Арматура А500С d12', 3)],
             TODAY + timedelta(2), 'Арматура для перекриття — термінова',
             'Коваль М.І.', '+380671119900', 'АА 1234 ВВ', self.suppliers[0]),
            (self.warehouses[2], self.foremen[2], 'high',
             [('Бетон В25 М350', 40)],
             TODAY + timedelta(1), 'Бетон для фундаментної плити ТРЦ',
             'Петров С.А.', '+380501119911', 'КА 5678 МВ', self.suppliers[2]),
        ]
        for wh, creator, prio, items_data, exp_date, note, drv, drv_ph, car, sup in transit_data:
            self._create_order_transit(wh, creator, prio, items_data, exp_date, note, drv, drv_ph, car, sup)

        # --- 4. У ЗАКУПІВЛІ (purchasing) ---
        purchasing_data = [
            (self.warehouses[3], self.foremen[3], 'high',
             [('Газобетон D500', 20), ('Цегла рядова М150', 1500)],
             TODAY + timedelta(4), 'Кладка зовнішніх стін БЦ Альфа', self.suppliers[3]),
            (self.warehouses[1], self.foremen[1], 'medium',
             [('Штукатурка Knauf MP75', 800)],
             TODAY + timedelta(5), 'Штукатурні роботи 4-й поверх', self.suppliers[4]),
            (self.warehouses[2], self.foremen[2], 'critical',
             [('Послуги крана 25т', 12), ('Бетононасос', 4)],
             TODAY + timedelta(2), 'Підйомно-монтажні роботи ТРЦ', self.suppliers[0]),
        ]
        for wh, creator, prio, items_data, exp_date, note, sup in purchasing_data:
            self._create_order_purchasing(wh, creator, prio, items_data, exp_date, note, sup)

        # --- 5. ПОГОДЖЕНІ (approved) ---
        approved_data = [
            (self.warehouses[1], self.foremen[0], 'high',
             [('Мембрана гідроізоляційна', 200), ('Керамзит фр. 10-20', 15)],
             TODAY + timedelta(6), 'Гідроізоляція покрівлі 5-го поверху'),
            (self.warehouses[3], self.foremen[4], 'medium',
             [('Балка металева HEA200', 30)],
             TODAY + timedelta(7), 'Металоконструкції для перекриття БЦ'),
        ]
        for wh, creator, prio, items_data, exp_date, note in approved_data:
            self._create_order_approved(wh, creator, prio, items_data, exp_date, note)

        # --- 6. НОВІ заявки (new) ---
        new_data = [
            (self.warehouses[1], self.foremen[0], 'medium',
             [('Цемент М-500', 300), ('Пісок річковий', 8)],
             TODAY + timedelta(5), 'Стяжка підлоги 5-й поверх'),
            (self.warehouses[2], self.foremen[2], 'high',
             [('Арматура А500С d20', 4), ('Дріт в\'язальний 1.2', 100)],
             TODAY + timedelta(3), 'Армування перекриття 2-го рівня'),
            (self.warehouses[3], self.foremen[3], 'low',
             [('Шлакоблок 390x190x188', 500)],
             TODAY + timedelta(10), 'Перегородки технічного поверху'),
            (self.warehouses[4], self.foremen[5], 'critical',
             [('Щебінь гранітний 5-20', 30), ('Пісок річковий', 15)],
             TODAY + timedelta(1), 'ТЕРМІНОВО: підготовка під\'їзду до об\'єкту'),
            (self.warehouses[1], self.foremen[1], 'medium',
             [('Пінопласт ПСБ-С25 100мм', 250), ('Мінвата Rockwool 100мм', 150)],
             TODAY + timedelta(8), 'Утеплення стін 6-го поверху'),
            (self.warehouses[2], self.foremen[2], 'high',
             [('Бетон В30 М400', 50), ('Послуги бетононасосу', 3)],
             TODAY + timedelta(4), 'Монолітні роботи — ядро жорсткості'),
        ]
        for wh, creator, prio, items_data, exp_date, note in new_data:
            self._create_order_new(wh, creator, prio, items_data, exp_date, note)

        self.stdout.write(f' > Заявки: {Order.objects.count()} шт. по всіх статусах.')

    # ── helpers для Orders ──

    def _make_order(self, wh, creator, prio, exp_date, note, status):
        return Order.objects.create(
            warehouse=wh, created_by=creator, status=status,
            priority=prio, expected_date=exp_date, note=note,
        )

    def _add_items(self, order, items_data, supplier=None):
        for mat_name, qty in items_data:
            mat = self._mat(mat_name)
            if not mat:
                continue
            sup_price = None
            if supplier:
                sp = SupplierPrice.objects.filter(supplier=supplier, material=mat).first()
                sup_price = sp.price if sp else mat.current_avg_price
            OrderItem.objects.create(
                order=order, material=mat,
                quantity=Decimal(str(qty)),
                supplier=supplier,
                supplier_price=sup_price,
            )

    def _mat(self, name):
        for m in self.materials:
            if m.name == name:
                return m
        return None

    def _add_comment(self, order, author, text, days_back=0):
        c = OrderComment(order=order, author=author, text=text)
        c.save()
        if days_back:
            OrderComment.objects.filter(pk=c.pk).update(
                created_at=timezone.now() - timedelta(days=days_back)
            )

    def _create_order_new(self, wh, creator, prio, items_data, exp_date, note):
        order = self._make_order(wh, creator, prio, exp_date, note, 'new')
        self._add_items(order, items_data)
        self._add_comment(order, creator,
            f'Створив заявку. Потрібно до {exp_date.strftime("%d.%m")}. {note}.', 0)
        self.all_orders.append(order)

    def _create_order_approved(self, wh, creator, prio, items_data, exp_date, note):
        order = self._make_order(wh, creator, prio, exp_date, note, 'approved')
        self._add_items(order, items_data)
        mgr = random.choice(self.managers)
        self._add_comment(order, creator, f'Прошу погодити заявку. {note}.', 3)
        self._add_comment(order, mgr, '✅ Заявку погоджено. Передано в закупівлю.', 1)
        self.all_orders.append(order)

    def _create_order_purchasing(self, wh, creator, prio, items_data, exp_date, note, supplier):
        order = self._make_order(wh, creator, prio, exp_date, note, 'purchasing')
        self._add_items(order, items_data, supplier=supplier)
        mgr = random.choice(self.managers)
        self._add_comment(order, creator, f'Потрібно терміново. {note}.', 5)
        self._add_comment(order, mgr, '✅ Погоджено. Відправлено в закупівлю.', 4)
        self._add_comment(order, mgr, f'🛒 Заявку передано постачальнику {supplier.name}. Очікуємо підтвердження.', 2)
        self.all_orders.append(order)

    def _create_order_transit(self, wh, creator, prio, items_data, exp_date, note, drv, drv_ph, car, supplier):
        full_note = f'{note}\n[Логістика] Водій: {drv_ph}, Авто: {car}'
        order = self._make_order(wh, creator, prio, exp_date, full_note, 'transit')
        self._add_items(order, items_data, supplier=supplier)
        mgr = random.choice(self.managers)
        self._add_comment(order, creator, f'Заявка сформована. {note}.', 7)
        self._add_comment(order, mgr, '✅ Погоджено.', 6)
        self._add_comment(order, mgr, f'🛒 У закупівлі, постачальник: {supplier.name}.', 4)
        self._add_comment(order, mgr, f'🚛 Вантаж відправлено. Водій: {drv} ({drv_ph}), авто: {car}.', 1)
        self.all_orders.append(order)

    def _create_order_completed(self, wh, creator, prio, items_data, exp_date, note):
        order = self._make_order(wh, creator, prio, exp_date, note, 'transit')
        sup = random.choice(self.suppliers)
        self._add_items(order, items_data, supplier=sup)
        mgr = random.choice(self.managers)
        self._add_comment(order, creator, f'Заявка на матеріали. {note}.', 14)
        self._add_comment(order, mgr, '✅ Погоджено.', 13)
        self._add_comment(order, mgr, f'🛒 У закупівлі, постачальник {sup.name}.', 11)
        self._add_comment(order, mgr, '🚛 Вантаж виїхав.', 10)

        # Проводимо через inventory — стає completed і оновлює залишки
        items_fact = {item.id: item.quantity for item in order.items.all()}
        try:
            inventory.process_order_receipt(order, items_fact, mgr, comment='Прийнято на склад по накладній')
        except Exception:
            order.status = 'completed'
            order.save()

        self._add_comment(order, creator, '📦 Матеріали прийнято, все в нормі.', 9)
        self.all_orders.append(order)

    def _create_order_rejected(self, wh, creator, prio, items_data, exp_date, note):
        order = self._make_order(wh, creator, prio, exp_date, note, 'new')
        self._add_items(order, items_data)
        mgr = random.choice(self.managers)
        self._add_comment(order, creator, f'Прошу погодити. {note}.', 5)
        self._add_comment(order, mgr, f'❌ Відхилено. Причина: {note.split("—")[-1].strip() if "—" in note else "не відповідає бюджету"}.', 4)
        order.status = 'rejected'
        order.save()
        self.all_orders.append(order)

    # ──────────────────────────────────────────────
    # TRANSFERS
    # ──────────────────────────────────────────────
    def _transfers(self):
        main = self.warehouses[0]
        targets = self.warehouses[1:]
        admin = self.admin

        transfer_plan = [
            (days_ago(55), self.warehouses[1], [('Цемент М-500', 1000), ('Арматура А500С d12', 1)]),
            (days_ago(48), self.warehouses[2], [('Бетон В25 М350', 30), ('Арматура А500С d16', 2)]),
            (days_ago(35), self.warehouses[3], [('Газобетон D500', 10), ('Цегла рядова М150', 1000)]),
            (days_ago(28), self.warehouses[1], [('Пінопласт ПСБ-С25 100мм', 100), ('Мінвата Rockwool 100мм', 80)]),
            (days_ago(18), self.warehouses[2], [('Арматура А500С d20', 2), ('Дріт в\'язальний 1.2', 80)]),
            (days_ago(10), self.warehouses[4], [('Щебінь гранітний 5-20', 15), ('Пісок річковий', 8)]),
            (days_ago(5),  self.warehouses[3], [('Штукатурка Knauf MP75', 300)]),
            (days_ago(2),  self.warehouses[1], [('Мембрана гідроізоляційна', 150)]),
        ]

        for t_date, target, items in transfer_plan:
            for mat_name, qty in items:
                mat = self._mat(mat_name)
                if not mat:
                    continue
                try:
                    inventory.create_transfer(
                        user=admin, material=mat,
                        source_warehouse=main, target_warehouse=target,
                        quantity=Decimal(str(qty)),
                        description=f'Переміщення: {mat_name} → {target.name}',
                        date=t_date,
                    )
                except Exception:
                    pass

        self.stdout.write(' > Переміщення між складами створено.')

    # ──────────────────────────────────────────────
    # WRITEOFFS / USAGE  (для звіту списань та графіків)
    # ──────────────────────────────────────────────
    def _writeoffs(self):
        usage_plan = []

        # OUT — використання матеріалів на роботах, розподілено по датах
        for wh in self.warehouses[1:4]:
            stages = list(wh.stages.all())
            if not stages:
                continue
            foreman = next(
                (f for f in self.foremen if wh in f.profile.warehouses.all()),
                self.foremen[0]
            )
            # 20 списань на кожен об'єкт за 60 днів → красивий OUT-графік
            for i in range(20):
                mat = random.choice(self.materials[:15])  # Основні матеріали
                stage = random.choice(stages)
                d = days_ago(random.randint(1, 60))
                qty = Decimal(str(round(random.uniform(1, 30), 3)))
                usage_plan.append((mat, wh, qty, foreman, 'OUT', stage, d,
                                   f'Використано на "{stage.name}"'))

        # LOSS — втрати/бій (~5 на об'єкт)
        for wh in self.warehouses[1:4]:
            stages = list(wh.stages.all())
            for _ in range(5):
                mat = random.choice(self.materials[:8])
                stage = random.choice(stages) if stages else None
                d = days_ago(random.randint(5, 45))
                qty = Decimal(str(round(random.uniform(0.5, 5), 3)))
                usage_plan.append((mat, wh, qty, self.foremen[0], 'LOSS', stage, d,
                                   'Втрати при транспортуванні / бій'))

        for mat, wh, qty, user, ttype, stage, d, desc in usage_plan:
            try:
                inventory.create_writeoff(
                    material=mat, warehouse=wh,
                    quantity=qty, user=user,
                    transaction_type=ttype,
                    description=desc,
                    stage=stage,
                    date=d,
                )
            except Exception:
                pass

        self.stdout.write(' > Списання та втрати згенеровано.')

    # ──────────────────────────────────────────────
    # AUDIT LOG
    # ──────────────────────────────────────────────
    def _audit_log(self):
        from django.contrib.contenttypes.models import ContentType
        order_ct = ContentType.objects.get_for_model(Order)

        entries = []
        completed_orders = Order.objects.filter(status='completed')[:5]
        for order in completed_orders:
            user = random.choice(self.managers)
            for action, new_val in [
                ('CREATE',       f'Order #{order.id} created'),
                ('ORDER_STATUS', 'approved'),
                ('ORDER_STATUS', 'purchasing'),
                ('ORDER_STATUS', 'transit'),
                ('ORDER_RECEIVED', 'completed'),
            ]:
                entries.append(AuditLog(
                    user=user, action_type=action,
                    content_type=order_ct, object_id=order.id,
                    new_value=new_val,
                ))

        AuditLog.objects.bulk_create(entries)
        self.stdout.write(f' > Журнал аудиту: {len(entries)} записів.')
