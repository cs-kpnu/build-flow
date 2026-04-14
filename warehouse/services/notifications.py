"""
Сервіс нотифікацій для зміни статусу заявок.
Підтримує Email та Telegram.
"""
import logging
import requests
from django.conf import settings
from django.core.mail import send_mail
from django.contrib.auth import get_user_model

logger = logging.getLogger('warehouse')

User = get_user_model()

# Людиночитані назви статусів
STATUS_LABELS = {
    'new': 'Нова',
    'rfq': 'Запит ціни (RFQ)',
    'approved': 'Погоджено',
    'purchasing': 'У закупівлі',
    'transit': 'В дорозі',
    'completed': 'Виконано / На складі',
    'rejected': 'Відхилено',
}

# Емодзі для кожного статусу
STATUS_EMOJI = {
    'new': '🆕',
    'rfq': '📋',
    'approved': '✅',
    'purchasing': '🛒',
    'transit': '🚚',
    'completed': '📦',
    'rejected': '🚫',
}


def _build_message(order, old_status, new_status, actor):
    """Формує текст повідомлення."""
    old_label = STATUS_LABELS.get(old_status, old_status)
    new_label = STATUS_LABELS.get(new_status, new_status)
    emoji = STATUS_EMOJI.get(new_status, '🔔')
    actor_name = actor.get_full_name() or actor.username if actor else 'Система'

    subject = f"{emoji} Заявка #{order.id}: {old_label} → {new_label}"

    body = (
        f"{emoji} Зміна статусу заявки #{order.id}\n\n"
        f"Склад: {order.warehouse.name}\n"
        f"Статус: {old_label} → {new_label}\n"
        f"Хто змінив: {actor_name}\n"
    )
    if order.expected_date:
        body += f"Очікувана дата: {order.expected_date.strftime('%d.%m.%Y')}\n"
    if order.note:
        body += f"Примітка: {order.note[:200]}\n"

    return subject, body


def send_email_notification(recipient_email, subject, body):
    """Надсилає email. Безпечно ковтає всі помилки."""
    if not recipient_email:
        return
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            fail_silently=False,
        )
    except Exception as exc:
        logger.warning("Email notification failed to %s: %s", recipient_email, exc)


def send_telegram_notification(chat_id, text):
    """Надсилає повідомлення через Telegram Bot API. Безпечно ковтає помилки."""
    if not chat_id:
        return
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
    if not token:
        logger.debug("TELEGRAM_BOT_TOKEN not set — skipping Telegram notification.")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
        if not resp.ok:
            logger.warning("Telegram notification failed (chat_id=%s): %s", chat_id, resp.text)
    except Exception as exc:
        logger.warning("Telegram notification error (chat_id=%s): %s", chat_id, exc)


def notify_order_status_change(order, old_status, new_status, actor=None):
    """
    Головна функція: надсилає email + Telegram всім, хто має бути сповіщений.

    Отримувачі:
    - Автор заявки (created_by)
    - Відповідальний за склад (warehouse.responsible_user) — якщо інший
    """
    if old_status == new_status:
        return

    subject, body = _build_message(order, old_status, new_status, actor)

    recipients = set()
    if order.created_by_id:
        recipients.add(order.created_by_id)
    if order.warehouse.responsible_user_id:
        recipients.add(order.warehouse.responsible_user_id)
    # Не сповіщаємо того, хто сам змінив статус
    if actor and actor.pk:
        recipients.discard(actor.pk)

    if not recipients:
        return

    users = User.objects.filter(pk__in=recipients).select_related('profile')
    for user in users:
        # Email
        if user.email:
            send_email_notification(user.email, subject, body)
        # Telegram
        chat_id = getattr(getattr(user, 'profile', None), 'telegram_chat_id', None)
        if chat_id:
            tg_text = (
                f"<b>{subject}</b>\n\n"
                + body.replace("\n", "\n")
            )
            send_telegram_notification(chat_id, tg_text)
