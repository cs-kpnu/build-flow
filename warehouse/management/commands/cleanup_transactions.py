"""
Команда очищення/архівування старих транзакцій.

Використання:
    python manage.py cleanup_transactions --days=365 --dry-run
    python manage.py cleanup_transactions --days=365 --soft-delete
    python manage.py cleanup_transactions --days=365 --hard-delete --confirm

Режими:
  --soft-delete  (default) — позначає транзакції як видалені (is_deleted=True).
  --hard-delete            — фізично видаляє з бази. Вимагає --confirm.
  --dry-run                — лише показує кількість записів, нічого не змінює.

Фільтри:
  --days N     — транзакції старіші за N днів (default: 365).
  --type TYPE  — тільки конкретний тип (IN / OUT / LOSS).
  --warehouse  — тільки для конкретного складу (pk).
"""
import logging
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from datetime import timedelta
from warehouse.models import Transaction

logger = logging.getLogger('warehouse')


class Command(BaseCommand):
    help = 'Архівує (soft-delete) або видаляє старі транзакції.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=365,
            help='Мінімальний вік транзакцій у днях (default: 365).'
        )
        parser.add_argument(
            '--type', dest='tx_type', choices=['IN', 'OUT', 'LOSS'], default=None,
            help='Фільтр по типу транзакції (необов\'язково).'
        )
        parser.add_argument(
            '--warehouse', type=int, default=None,
            help='Фільтр по ID складу (необов\'язково).'
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Не вносити зміни — тільки показати кількість записів.'
        )
        parser.add_argument(
            '--soft-delete', action='store_true', default=True,
            help='М\'яке видалення (is_deleted=True). Це поведінка за замовчуванням.'
        )
        parser.add_argument(
            '--hard-delete', action='store_true',
            help='Фізичне видалення з бази. Вимагає --confirm.'
        )
        parser.add_argument(
            '--confirm', action='store_true',
            help='Підтвердження для --hard-delete.'
        )

    def handle(self, *args, **options):
        days = options['days']
        tx_type = options['tx_type']
        warehouse_pk = options['warehouse']
        dry_run = options['dry_run']
        hard_delete = options['hard_delete']

        if hard_delete and not options['confirm']:
            raise CommandError(
                'Для фізичного видалення потрібне підтвердження: додайте --confirm'
            )

        cutoff_date = timezone.now() - timedelta(days=days)

        # Будуємо QuerySet зі звичайного менеджера (не soft-deleted)
        qs = Transaction.objects.filter(date__lt=cutoff_date.date())

        if tx_type:
            qs = qs.filter(transaction_type=tx_type)
        if warehouse_pk:
            qs = qs.filter(warehouse_id=warehouse_pk)

        # Виключаємо транзакції, що пов'язані з незавершеними заявками
        qs = qs.exclude(order__isnull=False, order__status__in=['new', 'approved', 'purchasing', 'transit'])

        count = qs.count()

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'[DRY RUN] Знайдено {count} транзакцій старіших за {days} днів. '
                    f'Дата зрізу: {cutoff_date.date()}. Без змін.'
                )
            )
            return

        if count == 0:
            self.stdout.write(self.style.SUCCESS('Транзакцій для очищення не знайдено.'))
            return

        if hard_delete:
            deleted, _ = qs.delete()
            msg = f'Фізично видалено {deleted} транзакцій старіших за {days} днів.'
            self.stdout.write(self.style.SUCCESS(msg))
            logger.info("cleanup_transactions hard-delete: %d rows, cutoff=%s", deleted, cutoff_date.date())
        else:
            # Soft-delete через bulk update
            updated = qs.update(is_deleted=True, deleted_at=timezone.now())
            msg = f'Soft-deleted {updated} транзакцій старіших за {days} днів.'
            self.stdout.write(self.style.SUCCESS(msg))
            logger.info("cleanup_transactions soft-delete: %d rows, cutoff=%s", updated, cutoff_date.date())
