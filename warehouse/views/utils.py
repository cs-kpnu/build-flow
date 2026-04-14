from django.db.models import Sum, Case, When, F, DecimalField, Value, Q
from django.http import Http404, JsonResponse
from django.contrib.auth.decorators import login_required
from ..models import Transaction, Warehouse, Material, AuditLog, UserProfile
from ..services.cache_utils import get_user_warehouse_ids, get_materials_for_select
import json
from decimal import Decimal

# ==============================================================================
# 1. ДОСТУП ТА БЕЗПЕКА
# ==============================================================================

def get_allowed_warehouses(user):
    """
    Повертає QuerySet складів, до яких користувач має доступ.
    Результат IDs беруться з кешу (cache_utils.get_user_warehouse_ids).
    """
    ids = get_user_warehouse_ids(user)
    if not ids:
        return Warehouse.objects.none()
    return Warehouse.objects.filter(pk__in=ids)

def restrict_warehouses_qs(qs, user, warehouse_field='warehouse'):
    """
    Фільтрує QuerySet, залишаючи тільки записи, що стосуються дозволених складів.
    - qs: Початковий QuerySet (Transaction, Order, тощо).
    - user: Користувач.
    - warehouse_field: Назва поля FK на Warehouse в моделі (default='warehouse').
    """
    if user.is_superuser or user.is_staff:
        return qs
        
    allowed_whs = get_allowed_warehouses(user)
    
    # Формуємо фільтр динамічно: warehouse__in=allowed_whs
    filter_kwargs = {f"{warehouse_field}__in": allowed_whs}
    
    return qs.filter(**filter_kwargs)

def enforce_warehouse_access_or_404(user, warehouse):
    """
    Перевіряє доступ користувача до конкретного складу.
    Якщо доступу немає - піднімає Http404.
    """
    # Якщо warehouse передано як ID, дістаємо об'єкт (або перевіряємо ID в allowed)
    # Але для спрощення припускаємо, що це об'єкт.
    # Якщо це ID, треба спочатку отримати об'єкт або перевірити входження ID.
    
    allowed = get_allowed_warehouses(user)
    
    # Перевірка: чи є цей склад у дозволених
    if not allowed.filter(pk=warehouse.pk).exists():
        raise Http404("Склад не знайдено або доступ заборонено.")

def get_user_warehouses(user):
    """
    Alias for get_allowed_warehouses to maintain backward compatibility if used elsewhere.
    Повертає QuerySet складів, доступних користувачу.
    """
    return get_allowed_warehouses(user)

def check_access(user, warehouse):
    """
    Перевіряє, чи має користувач доступ до конкретного складу (об'єкт або ID).
    Використовує кешовані IDs — без зайвого DB-запиту.
    """
    if user.is_superuser or user.is_staff:
        return True

    wh_id = warehouse.id if hasattr(warehouse, 'id') else warehouse
    allowed_ids = get_user_warehouse_ids(user)
    return wh_id in allowed_ids

# ==============================================================================
# 2. HELPER FUNCTIONS
# ==============================================================================

def is_transfer_tx(tx):
    """
    Перевіряє, чи є транзакція частиною переміщення.
    Повертає True, якщо це переміщення (має transfer_group_id).
    """
    return tx.transfer_group_id is not None

def work_writeoffs_qs(qs):
    """
    Фільтрує QuerySet, залишаючи тільки реальні операційні витрати/списання.
    ВИКЛЮЧАЄ переміщення (трансфери), навіть якщо вони мають тип OUT.
    
    Залишаються:
    - OUT (Витрата на роботи)
    - LOSS (Бій/Втрата)
    """
    return qs.filter(
        transaction_type__in=['OUT', 'LOSS'],
        transfer_group_id__isnull=True
    )

# ==============================================================================
# 3. ЛОГІКА БАЛАНСУ ТА СКЛАДУ
# ==============================================================================

def get_warehouse_balance(warehouse):
    """
    Рахує залишки по складу.
    Формула: SUM(IN) - SUM(OUT) - SUM(LOSS).
    
    Повертає словник {Material_Object: Decimal_quantity}.
    Використовує in_bulk для оптимізації запитів до БД.
    """
    # 1. Агрегація по material_id
    qs = Transaction.objects.filter(warehouse=warehouse).values('material').annotate(
        total_in=Sum('quantity', filter=Q(transaction_type='IN')),
        total_out=Sum('quantity', filter=Q(transaction_type__in=['OUT', 'LOSS']))
    )
    
    # 2. Збираємо проміжні дані {material_id: qty}
    temp_balance = {}
    material_ids = []
    
    for item in qs:
        in_qty = item['total_in'] or Decimal("0.000")
        out_qty = item['total_out'] or Decimal("0.000")
        
        # Розрахунок залишку (Decimal)
        current_stock = in_qty - out_qty
        
        mat_id = item['material']
        temp_balance[mat_id] = current_stock
        material_ids.append(mat_id)
        
    # 3. Витягуємо об'єкти Material одним запитом (in_bulk)
    materials_map = Material.objects.in_bulk(material_ids)
    
    # 4. Формуємо фінальний словник {Material: qty}
    balance = {}
    for mat_id, qty in temp_balance.items():
        if mat_id in materials_map:
            # Використовуємо об'єкт Material як ключ
            balance[materials_map[mat_id]] = qty
        
    return balance

def get_multi_warehouse_balance(warehouses):
    """
    Батч-версія get_warehouse_balance для кількох складів.
    Повертає: {warehouse_id: {Material: Decimal}}
    Виконує 2 запити незалежно від кількості складів.
    """
    wh_list = list(warehouses)
    if not wh_list:
        return {}

    qs = Transaction.objects.filter(
        warehouse__in=wh_list,
        transaction_type__in=['IN', 'OUT', 'LOSS']
    ).values('warehouse_id', 'material_id').annotate(
        total_in=Sum('quantity', filter=Q(transaction_type='IN')),
        total_out=Sum('quantity', filter=Q(transaction_type__in=['OUT', 'LOSS']))
    )

    material_ids = {row['material_id'] for row in qs}
    materials_map = Material.objects.filter(id__in=material_ids).in_bulk()

    result = {wh.id: {} for wh in wh_list}
    for row in qs:
        mat = materials_map.get(row['material_id'])
        if mat:
            qty = (row['total_in'] or Decimal("0.000")) - (row['total_out'] or Decimal("0.000"))
            result[row['warehouse_id']][mat] = qty

    return result


def get_stock_json(user=None):
    """
    Повертає JSON з залишками по всіх складах.
    Використовується для JS-валідації у формах (TransactionForm, TransferForm).
    Format: {warehouse_id: {name: "...", items: {mat_id: "qty_string", ...}}}
    """
    if user is None:
        warehouses = Warehouse.objects.all()
    elif user.is_superuser or user.is_staff:
        warehouses = Warehouse.objects.all()
    else:
        warehouses = get_allowed_warehouses(user)

    wh_list = list(warehouses)
    multi_balance = get_multi_warehouse_balance(wh_list)

    data = {}
    for wh in wh_list:
        balance_map = multi_balance.get(wh.id, {})
        items_dict = {mat.id: str(qty) for mat, qty in balance_map.items()}
        data[wh.id] = {
            'name': wh.name,
            'items': items_dict
        }

    return json.dumps(data)

# ==============================================================================
# 4. АУДИТ ТА ЖУРНАЛИ
# ==============================================================================

def capture_order_snapshot(order):
    """
    Знімає поточні значення відстежуваних полів Order.
    Повертає dict {field: display_value} для подальшого порівняння.
    """
    return {
        'status':        (order.status, order.get_status_display()),
        'priority':      (order.priority, order.get_priority_display()),
        'note':          (order.note, order.note),
        'expected_date': (
            str(order.expected_date) if order.expected_date else None,
            order.expected_date.strftime('%d.%m.%Y') if order.expected_date else '—',
        ),
        'warehouse_id':  (
            order.warehouse_id,
            str(order.warehouse) if order.warehouse_id else '—',
        ),
    }


# Мітки полів Order для відображення в журналі
ORDER_FIELD_LABELS = {
    'status':        'Статус',
    'priority':      'Пріоритет',
    'note':          'Примітка',
    'expected_date': 'Очікувана дата',
    'warehouse_id':  'Склад',
}


def compute_order_diff(old_snapshot, new_order):
    """
    Порівнює snapshot (до збереження) з поточним станом order.
    Повертає dict змінених полів або порожній dict.

    Формат: {field: {old: "...", new: "...", label: "..."}}
    """
    new_snapshot = capture_order_snapshot(new_order)
    changed = {}
    for field, (old_raw, old_display) in old_snapshot.items():
        new_raw, new_display = new_snapshot[field]
        if str(old_raw) != str(new_raw):
            changed[field] = {
                'old': old_display,
                'new': new_display,
                'label': ORDER_FIELD_LABELS.get(field, field),
            }
    return changed


def log_audit(request, action_type, affected_object=None, old_val=None, new_val=None,
              changed_fields=None):
    """
    Записує дію в журнал аудиту (AuditLog).
    changed_fields: dict {field: {old, new, label}} для поле-рівневого логування.
    Fail-safe версія.
    """
    user = None
    ip = None

    if request:
        # 1. User extraction (fail-safe)
        req_user = getattr(request, 'user', None)
        if req_user and getattr(req_user, 'is_authenticated', False):
            user = req_user
        
        # 2. IP extraction (fail-safe)
        meta = getattr(request, 'META', {}) or {}
        
        x_forwarded_for = meta.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            # Беремо перший IP зі списку проксі
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = meta.get('REMOTE_ADDR')
    
    # 3. Smart creation: pass only allowed fields
    import logging
    logger = logging.getLogger('warehouse')

    try:
        allowed_fields = {f.name for f in AuditLog._meta.fields}
    except (AttributeError, TypeError) as e:
        logger.debug(f"Could not get AuditLog fields: {e}")
        allowed_fields = {'user', 'action_type', 'old_value', 'new_value', 'ip_address'}

    audit_kwargs = {
        'user': user,
        'action_type': action_type,
        'old_value': str(old_val) if old_val is not None else None,
        'new_value': str(new_val) if new_val is not None else None,
        'ip_address': ip,
    }

    if 'changed_fields' in allowed_fields and changed_fields:
        audit_kwargs['changed_fields'] = changed_fields

    if 'content_type' in allowed_fields and affected_object is not None:
        from django.contrib.contenttypes.models import ContentType
        try:
            ct = ContentType.objects.get_for_model(affected_object)
            audit_kwargs['content_type'] = ct
            audit_kwargs['object_id'] = affected_object.pk
        except Exception:
            pass

    try:
        AuditLog.objects.create(**audit_kwargs)
    except (ValueError, TypeError) as e:
        # Не блокуємо основну операцію через помилку логування
        logger.warning(f"Failed to create AuditLog: {e}")

def enrich_transfers(queryset):
    """
    Групує транзакції переміщень у зручний формат для журналу.
    Зв'язує пари транзакцій (OUT + IN) по transfer_group_id.
    """
    grouped_transfers = {}
    
    # Беремо тільки транзакції з transfer_group_id
    transfers_raw = queryset.filter(transfer_group_id__isnull=False).select_related('warehouse', 'material', 'created_by').order_by('-created_at')
    
    for tx in transfers_raw:
        gid = tx.transfer_group_id
        
        if gid not in grouped_transfers:
            grouped_transfers[gid] = {
                'id': str(gid),
                'date': tx.created_at,
                'created_at': tx.created_at,
                'material': tx.material.name,
                'quantity': tx.quantity,
                'unit': tx.material.unit,
                'initiator': tx.created_by.get_full_name() if tx.created_by else "Система",
                'source_wh': None,
                'target_wh': None,
                'description': tx.description,
                'status_label': 'Виконано',
                'status_class': 'success'
            }
        
        # Визначаємо напрямок по типу IN/OUT
        # OUT - це джерело, IN - це призначення
        if tx.transaction_type == 'OUT':
            grouped_transfers[gid]['source_wh'] = tx.warehouse.name
        elif tx.transaction_type == 'IN':
            grouped_transfers[gid]['target_wh'] = tx.warehouse.name
            
    return list(grouped_transfers.values())

from ..decorators import rate_limit


@login_required
@rate_limit(requests_per_minute=60, key_prefix='ajax_stock')
def ajax_warehouse_stock(request, warehouse_id=None):
    """
    AJAX API: Повертає залишки по конкретному складу.
    URL: /ajax/warehouse/<int:warehouse_id>/stock/ (REST-style)
    URL: /ajax/warehouse-stock/?warehouse_id=123 (Legacy support)
    
    JSON Response:
    {
      "warehouse_id": 123,
      "items": [
        {"material_id": 10, "name": "Цемент", "unit": "кг", "qty": "500.000"},
        ...
      ]
    }
    """
    # 1. Визначаємо warehouse_id з аргументів або GET-параметрів
    if warehouse_id is None:
        warehouse_id = request.GET.get('warehouse_id')
    
    if not warehouse_id:
        return JsonResponse({'error': 'Missing warehouse_id'}, status=400)
    
    try:
        wh_id_int = int(warehouse_id)
    except (TypeError, ValueError):
        # ВИПРАВЛЕНО: повертаємо 404 замість 400 для нечислового ID, щоб відповідати тестам
        return JsonResponse({'error': 'Invalid ID'}, status=404)
        
    try:
        warehouse = Warehouse.objects.get(pk=wh_id_int)
        # Перевірка доступу
        enforce_warehouse_access_or_404(request.user, warehouse)
    except (Warehouse.DoesNotExist, Http404):
        # Якщо склад не знайдено або немає доступу - повертаємо 404 (щоб не світити наявність)
        return JsonResponse({}, status=404)
    
    # Розрахунок балансу
    balance_map = get_warehouse_balance(warehouse)
    
    items = []
    
    for mat, qty in balance_map.items():
        if qty != 0:
            items.append({
                "material_id": mat.id,
                "name": mat.name,
                "unit": mat.unit,
                "qty": str(qty) # Серіалізуємо Decimal як рядок
            })
    
    # Сортуємо список за назвою матеріалу
    items.sort(key=lambda x: x['name'])
        
    return JsonResponse({
        "warehouse_id": warehouse.id,
        "items": items
    })

@login_required
@rate_limit(requests_per_minute=120, key_prefix='ajax_materials')
def ajax_materials(request):
    """
    AJAX API: Пошук матеріалів (Autocomplete).
    URL: /ajax/materials/?q=term
    
    JSON Response:
    {
      "items": [
        {"id": 1, "name": "Цемент", "unit": "кг", "article": "CEM-001"},
        ...
      ]
    }
    """
    query = (request.GET.get('q') or request.GET.get('term') or '').strip().lower()

    # Беремо з кешу (уникаємо DB-запиту при кожному натисканні клавіші)
    all_items = get_materials_for_select()

    if query:
        items = [
            m for m in all_items
            if query in m['name'].lower()
            or (m['article'] and query in m['article'].lower())
        ][:50]
    else:
        items = all_items[:50]

    return JsonResponse({'items': items})