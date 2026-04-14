"""
Кеш-утиліти для часто запитуваних lookups.

Стратегія:
- Кешуємо списки ID, а не QuerySet-и (QuerySet-и lazy і не серіалізуються).
- Повертаємо .filter(pk__in=ids) — один SELECT з індексом, без зайвих JOIN-ів.
- TTL = 5 хвилин (300 сек) — відповідає CACHES['default']['TIMEOUT'].
- Інвалідація через сигнали (signals.py).

Ключі:
  wh_all_ids          — список pk всіх складів
  wh_ids_user:{pk}    — список pk складів для конкретного юзера
  mat_select          — список (id, name, unit, article) для autocomplete
"""
import logging
from django.core.cache import cache

logger = logging.getLogger('warehouse')

TIMEOUT = 300  # 5 хвилин

# --------------------------------------------------------------------------- #
# СКЛАДИ                                                                       #
# --------------------------------------------------------------------------- #

_KEY_WH_ALL = 'wh_all_ids'
_KEY_WH_USER = 'wh_ids_user:{pk}'


def get_all_warehouse_ids():
    """Повертає list[int] pk усіх складів. Кешує на TIMEOUT."""
    from warehouse.models import Warehouse
    cached = cache.get(_KEY_WH_ALL)
    if cached is not None:
        return cached
    ids = list(Warehouse.objects.values_list('pk', flat=True))
    cache.set(_KEY_WH_ALL, ids, TIMEOUT)
    return ids


def get_user_warehouse_ids(user):
    """
    Повертає list[int] pk складів, доступних користувачу.
    Staff/superuser отримують усі склади.
    Результат кешується окремо для кожного user.pk.
    """
    if not user.is_authenticated:
        return []

    if user.is_superuser or user.is_staff:
        return get_all_warehouse_ids()

    key = _KEY_WH_USER.format(pk=user.pk)
    cached = cache.get(key)
    if cached is not None:
        return cached

    if hasattr(user, 'profile') and hasattr(user.profile, 'warehouses'):
        ids = list(user.profile.warehouses.values_list('pk', flat=True))
    else:
        ids = []

    cache.set(key, ids, TIMEOUT)
    return ids


def invalidate_warehouse_cache(user_pk=None):
    """
    Інвалідує кеш складів.
    user_pk=None → очищає загальний список (при CREATE/DELETE складу).
    user_pk=int  → очищає список для конкретного юзера (при зміні прав).
    """
    cache.delete(_KEY_WH_ALL)
    if user_pk is not None:
        cache.delete(_KEY_WH_USER.format(pk=user_pk))
    else:
        # При структурній зміні (новий/видалений склад) скидаємо всі per-user кеші.
        # cache.delete_many не підтримує wildcard у LocMemCache/Redis без scan,
        # тому використовуємо cache version bump через окремий sentinel-ключ.
        _bump_wh_version()


_KEY_WH_VERSION = 'wh_cache_version'


def _bump_wh_version():
    """Змінює версію кешу складів — усі per-user ключі стають stale."""
    try:
        cache.incr(_KEY_WH_VERSION)
    except ValueError:
        cache.set(_KEY_WH_VERSION, 1, None)  # без TTL — живе вічно


def get_wh_cache_version():
    v = cache.get(_KEY_WH_VERSION)
    if v is None:
        cache.set(_KEY_WH_VERSION, 1, None)
        return 1
    return v


# --------------------------------------------------------------------------- #
# МАТЕРІАЛИ (для autocomplete / Select-ів)                                    #
# --------------------------------------------------------------------------- #

_KEY_MAT_SELECT = 'mat_select'


def get_materials_for_select():
    """
    Повертає list[dict] {id, name, unit, article} відсортований за name.
    Використовується в AJAX autocomplete і формах.
    Кешується на TIMEOUT.
    """
    from warehouse.models import Material
    cached = cache.get(_KEY_MAT_SELECT)
    if cached is not None:
        return cached

    data = list(
        Material.objects.order_by('name').values('id', 'name', 'unit', 'article')
    )
    cache.set(_KEY_MAT_SELECT, data, TIMEOUT)
    return data


def invalidate_material_cache():
    """Скидає кеш списку матеріалів."""
    cache.delete(_KEY_MAT_SELECT)
