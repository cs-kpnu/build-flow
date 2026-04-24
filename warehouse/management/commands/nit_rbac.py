"""
init_rbac — Ініціалізація груп користувачів та прав доступу (RBAC).

Групи:
  Manager    — менеджери: повний доступ до заявок, транзакцій, матеріалів, звітів.
  Logistics  — логісти: перегляд та зміна статусів (transit), перегляд складів.
  Foreman    — прораби: перегляд, створення заявок, додавання транзакцій.
  Finance    — фінансисти: перегляд звітів та всіх операцій (read-only).

Примітка: головний контроль доступу в додатку реалізовано через user.is_staff,
user.profile.warehouses і кастомні декоратори. Ці групи використовуються для
тонкого налаштування через Django Permission system (has_perm) і admin-сайту.
"""
import logging
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from warehouse.models import Order, Transaction, Material, Warehouse, Supplier, AuditLog

logger = logging.getLogger('warehouse')


def _get_perms(*codenames):
    """Повертає QuerySet Permission для вказаних codenames."""
    return Permission.objects.filter(codename__in=codenames)


class Command(BaseCommand):
    help = 'Ініціалізація груп користувачів та прав доступу (RBAC)'

    def handle(self, *args, **options):
        self._setup_group(
            name='Manager',
            description='Менеджери: повний доступ до заявок, транзакцій, матеріалів.',
            permissions=[
                # Order
                'add_order', 'change_order', 'delete_order', 'view_order',
                # Transaction
                'add_transaction', 'change_transaction', 'delete_transaction', 'view_transaction',
                # Material
                'add_material', 'change_material', 'delete_material', 'view_material',
                # Warehouse
                'add_warehouse', 'change_warehouse', 'view_warehouse',
                # Supplier
                'add_supplier', 'change_supplier', 'view_supplier',
                # AuditLog
                'view_auditlog',
            ]
        )

        self._setup_group(
            name='Logistics',
            description='Логісти: перегляд та управління доставками.',
            permissions=[
                'view_order', 'change_order',
                'view_transaction',
                'view_warehouse',
                'view_material',
            ]
        )

        self._setup_group(
            name='Foreman',
            description='Прораби: створення заявок, додавання транзакцій (списань).',
            permissions=[
                'add_order', 'view_order',
                'add_transaction', 'view_transaction',
                'view_warehouse',
                'view_material',
            ]
        )

        self._setup_group(
            name='Finance',
            description='Фінансисти: перегляд усіх операцій та звітів (read-only).',
            permissions=[
                'view_order',
                'view_transaction',
                'view_warehouse',
                'view_material',
                'view_supplier',
                'view_auditlog',
            ]
        )

        self.stdout.write(self.style.SUCCESS(
            'OK. Ролі та права успішно налаштовані. '
            'Призначте групи користувачам через Адмінку або команду.'
        ))

    def _setup_group(self, name, description, permissions):
        group, created = Group.objects.get_or_create(name=name)
        action = 'Створена' if created else 'Оновлена'

        perms = _get_perms(*permissions)
        found = list(perms)
        missing = set(permissions) - {p.codename for p in found}

        group.permissions.set(found)

        self.stdout.write(
            f"  Група '{name}' [{action}]: "
            f"{len(found)} прав призначено."
        )
        if missing:
            logger.warning("init_rbac: permissions not found for group '%s': %s", name, missing)
            self.stdout.write(
                self.style.WARNING(f"    ⚠ Не знайдено: {missing}")
            )
