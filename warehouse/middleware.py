"""
Middleware для безпеки проекту Budsklad ERP.

CSPMiddleware — додає заголовок Content-Security-Policy до всіх відповідей.

Стратегія:
- Явний allowlist CDN-джерел, що використовуються у шаблонах.
- 'unsafe-inline' для script-src: шаблони мають inline-скрипти (Chart.js ініціалізація,
  Tom Select тощо). Для усунення 'unsafe-inline' потрібні nonces — окрема задача.
- Суворі обмеження на object-src, base-uri, frame-ancestors.
- Налаштовується через settings.CSP_* змінні.
"""
from django.conf import settings


_CDNS = [
    "cdn.jsdelivr.net",
    "cdnjs.cloudflare.com",
    "unpkg.com",
    "api.qrserver.com",
]

# Побудова директив
_SCRIPT_CDNS = " ".join(f"https://{d}" for d in _CDNS if d != "api.qrserver.com")
_STYLE_CDNS = " ".join(f"https://{d}" for d in _CDNS if d not in ("api.qrserver.com", "unpkg.com"))
_IMG_CDNS = " ".join(f"https://{d}" for d in _CDNS)

_DEFAULT_DIRECTIVES = {
    "default-src":   "'self'",
    "script-src":    f"'self' 'unsafe-inline' {_SCRIPT_CDNS}",
    "style-src":     f"'self' 'unsafe-inline' {_STYLE_CDNS}",
    "img-src":       f"'self' data: blob: {_IMG_CDNS}",
    "font-src":      f"'self' {_STYLE_CDNS}",
    "connect-src":   "'self'",
    "frame-src":     "'none'",
    "frame-ancestors": "'none'",
    "object-src":    "'none'",
    "base-uri":      "'self'",
    "form-action":   "'self'",
}


def _build_policy(directives: dict) -> str:
    return "; ".join(f"{k} {v}" for k, v in directives.items())


class CSPMiddleware:
    """
    Додає Content-Security-Policy заголовок до кожної HTML-відповіді.

    Пропускає відповіді без Content-Type: text/html (медіа, JSON, Excel тощо).
    Режим:
      - CSP_REPORT_ONLY = True  → Content-Security-Policy-Report-Only (не блокує)
      - CSP_REPORT_ONLY = False → Content-Security-Policy (блокує)

    Кастомізація директив: CSP_EXTRA = {'connect-src': "'self' wss://..."}
    """

    def __init__(self, get_response):
        self.get_response = get_response
        report_only = getattr(settings, 'CSP_REPORT_ONLY', False)
        self.header_name = (
            'Content-Security-Policy-Report-Only' if report_only
            else 'Content-Security-Policy'
        )
        # Дозволяє розширити директиви з settings.py без зміни middleware
        extra = getattr(settings, 'CSP_EXTRA', {})
        directives = {**_DEFAULT_DIRECTIVES, **extra}
        self.policy = _build_policy(directives)

    def __call__(self, request):
        response = self.get_response(request)
        content_type = response.get('Content-Type', '')
        if 'text/html' in content_type:
            response.setdefault(self.header_name, self.policy)
        return response
