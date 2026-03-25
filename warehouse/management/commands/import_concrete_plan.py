from django.core.management.base import BaseCommand
from warehouse.models import Material, Category, Warehouse, ConstructionStage, StageLimit

class Command(BaseCommand):
    help = 'Імпорт інженерного плану (Кошторис на бетон)'

    def handle(self, *args, **options):
        self.stdout.write("🏗️ Починаємо імпорт плану SAP...")

        # 1. Створюємо/Знаходимо об'єкт (Склад)
        wh_name = "ЖК 'Мрія' Секція 1" 
        warehouse, _ = Warehouse.objects.get_or_create(name=wh_name, defaults={'budget_limit': 5000000})
        
        # 2. Матеріал (Бетон)
        cat, _ = Category.objects.get_or_create(name="Бетон та Розчини")
        concrete, _ = Material.objects.get_or_create(
            name="Бетон В25 П3 (М350)", 
            defaults={'article': 'CON-B25', 'unit': 'м3', 'current_avg_price': 2850.00, 'category': cat}
        )

        # 3. ДАНІ З ТВОЄЇ ТАБЛИЦІ
        # Формат: "Назва Етапу": {"тип_конструктиву": кількість_кубів}
        plan_data = {
            "0. Фундамент (Плита)": {"horizontal": 150.5}, 
            "1. Поверх (Стіни/Колони)": {"vertical": 45.0},
            "1. Поверх (Перекриття)": {"horizontal": 62.0},
            "2. Поверх (Стіни/Колони)": {"vertical": 42.0},
            "2. Поверх (Перекриття)": {"horizontal": 62.0},
            "3. Поверх (Стіни/Колони)": {"vertical": 42.0},
            "3. Поверх (Перекриття)": {"horizontal": 62.0},
            "4. Дах (Парапети)": {"vertical": 15.0},
        }

        for stage_raw_name, limits in plan_data.items():
            # Створюємо етап в БД
            stage, created = ConstructionStage.objects.get_or_create(name=stage_raw_name, warehouse=warehouse)

            for c_type, qty in limits.items():
                # Створюємо ліміт (План) — construct_type видалено з моделі
                StageLimit.objects.update_or_create(
                    stage=stage,
                    material=concrete,
                    defaults={'planned_quantity': qty}
                )
                self.stdout.write(f"  ✅ {stage_raw_name} [{c_type}]: План {qty} м3")

        self.stdout.write(self.style.SUCCESS('✅ Кошторис успішно завантажено! Можна працювати.'))