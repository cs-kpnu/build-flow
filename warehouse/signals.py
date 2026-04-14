from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import pre_save
from django.dispatch import receiver
import logging

# Імпорт з warehouse.views.utils (де файл лежить фізично)
from warehouse.views.utils import log_audit

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


from django.db.models.signals import post_save as _post_save


@receiver(_post_save, sender='warehouse.Order')
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