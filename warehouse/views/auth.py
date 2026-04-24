"""
Кастомний login view з rate limiting.

Обмежує кількість спроб входу: 10 спроб на 5 хвилин з однієї IP.
При перевищенні повертає HTTP 429 з повідомленням замість JSON.
"""
from django.contrib.auth.views import LoginView
from django.http import HttpResponse
from django.core.cache import cache
import logging

logger = logging.getLogger('warehouse')

_LOGIN_RATE_LIMIT = 10       # спроб
_LOGIN_RATE_WINDOW = 300     # 5 хвилин


def _get_client_ip(request):
    """Витягує реальний IP клієнта (з урахуванням проксі)."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


class RateLimitedLoginView(LoginView):
    """
    Django LoginView з IP-based rate limiting.
    Рахує POST-запити (спроби логіну) — GET (відображення форми) не рахуються.
    """
    template_name = 'registration/login.html'

    def dispatch(self, request, *args, **kwargs):
        if request.method == 'POST':
            ip = _get_client_ip(request)
            cache_key = f'login_attempts:{ip}'
            attempts = cache.get(cache_key, 0)

            if attempts >= _LOGIN_RATE_LIMIT:
                logger.warning(
                    "Login rate limit exceeded for IP %s (%d attempts in %ds)",
                    ip, attempts, _LOGIN_RATE_WINDOW,
                )
                return HttpResponse(
                    "Забагато спроб входу. Спробуйте через 5 хвилин.",
                    status=429,
                    content_type='text/plain; charset=utf-8',
                )

            # Збільшуємо лічильник (TTL не оновлюється при повторному set — use add+incr)
            if attempts == 0:
                cache.set(cache_key, 1, timeout=_LOGIN_RATE_WINDOW)
            else:
                cache.incr(cache_key)

        return super().dispatch(request, *args, **kwargs)
