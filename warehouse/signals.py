from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import pre_save, post_save, post_delete, m2m_changed
from django.dispatch import receiver
import logging

# Імпорт з warehouse.views.utils (де файл лежить фізично)
from warehouse.views.utils import log_audit
from warehouse.services.cache_utils import (
    invalidate_warehouse_cache,
    invalidate_material_cache,
)

logger = logging.getLogger('warehouse')


@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    log_audit(request, 'LOGIN', user, new_val="Успішний вхід")


@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    log_audit(request, 'LOGOUT', user, new_val="Вихід з системи")


@receiver(user_login_failed)
def log_user_login_failed(sender, credentials, request, **kwargs):
    username = credentials.get('username', '???')
    logger.warning("Failed login attempt for username: %s", username)


@receiver(pre_save, sender='warehouse.Order')
def order_status_change_notification(sender, instance, **kwargs):
    """
    Відправляє email/Telegram нотифікацію при зміні статусу заявки.
    Зберігаємо старий статус у self._old_status для post_save.
    """
    if not instance.pk:
        # Нова заявка — нотифікація не потрібна
        instance._old_status = None
        return

    try:
        old_instance = sender.objects.get(pk=instance.pk)
        instance._old_status = old_instance.status
    except sender.DoesNotExist:
        instance._old_status = None


@receiver(post_save, sender='warehouse.Order')
def order_status_changed_send_notification(sender, instance, created, **kwargs):
    """
    Після збереження — якщо статус змінився, відправляємо нотифікацію.
    """
    if created:
        return

    old_status = getattr(instance, '_old_status', None)
    new_status = instance.status

    if old_status is None or old_status == new_status:
        return

    # Відкладений імпорт, щоб уникнути циклічних залежностей
    from warehouse.services.notifications import notify_order_status_change

    # actor зберігається у _actor атрибуті (якщо view його встановив)
    actor = getattr(instance, '_actor', None)

    try:
        notify_order_status_change(instance, old_status, new_status, actor=actor)
    except Exception as exc:
        logger.error("Notification error for Order #%s: %s", instance.pk, exc)


# ==============================================================================
# CACHE INVALIDATION SIGNALS
# ==============================================================================

@receiver(post_save, sender='warehouse.Warehouse')
@receiver(post_delete, sender='warehouse.Warehouse')
def invalidate_warehouse_on_change(sender, instance, **kwargs):
    """Скидає кеш складів при будь-якій зміні/видаленні."""
    invalidate_warehouse_cache()


@receiver(post_save, sender='warehouse.Material')
@receiver(post_delete, sender='warehouse.Material')
def invalidate_material_on_change(sender, instance, **kwargs):
    """Скидає кеш матеріалів при будь-якій зміні/видаленні."""
    invalidate_material_cache()


@receiver(m2m_changed, sender='warehouse.UserProfile_warehouses')
def invalidate_user_warehouse_cache(sender, instance, action, **kwargs):
    """
    Скидає per-user кеш при зміні M2M warehouses у профілі.
    instance може бути UserProfile або Warehouse залежно від reverse=True/False.
    """
    if action in ('post_add', 'post_remove', 'post_clear'):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        if hasattr(instance, 'user_id'):
            # instance — UserProfile
            invalidate_warehouse_cache(user_pk=instance.user_id)
        elif isinstance(instance, User):
            invalidate_warehouse_cache(user_pk=instance.pk)
        else:
            # Не знаємо хто — скидаємо загальний
            invalidate_warehouse_cache()