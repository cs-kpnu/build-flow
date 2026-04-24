from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Sum, F, DecimalField, Count, Q, Case, When, Value, Avg, ExpressionWrapper
from django.db.models.functions import TruncMonth, TruncDay
from django.http import HttpResponse, Http404
from datetime import timedelta
import datetime
from django.utils import timezone
import json
from decimal import Decimal, ROUND_HALF_UP

from ..models import Transaction, Order, OrderItem, Warehouse, Material, Supplier, AuditLog
from ..decorators import staff_required
from ..services.excel_utils import create_excel_response, sanitize_cell


def _parse_date(value):
    """Безпечно парсить рядок дати з GET-параметра. Повертає None при помилці."""
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value).strip())
    except (ValueError, TypeError):
        return None


def _sanitize_cell(value):
    """Зворотня сумісність — делегує до excel_utils.sanitize_cell."""
    return sanitize_cell(value)
from ..forms import PeriodReportForm
from .utils import (
    get_user_warehouses,
    get_warehouse_balance,
    get_multi_warehouse_balance,
    enrich_transfers,
    work_writeoffs_qs,
    get_allowed_warehouses,
    restrict_warehouses_qs,
    enforce_warehouse_access_or_404
)

# ==============================================================================
# ГОЛОВНИЙ ДАШБОРД АНАЛІТИКИ
# ==============================================================================

@staff_required
def reports_dashboard(request):
    """
    Головна сторінка розділу "Звіти".
    Відображає загальні KPI та графіки витрат.
    ВИКЛЮЧАЄ трансфери з розрахунку витрачених грошей.
    """
    # Вираз для безпечного множення Float * Decimal
    spent_expr = ExpressionWrapper(
        F('quantity') * F('price'),
        output_field=DecimalField(max_digits=14, decimal_places=2)
    )
    
    # Фільтруємо транзакції по доступу до складів
    base_qs = restrict_warehouses_qs(Transaction.objects.all(), request.user)
    
    # 1. Загальні витрати (Гроші)
    # Використовуємо work_writeoffs_qs, щоб виключити переміщення
    total_spent = work_writeoffs_qs(base_qs).aggregate(
        s=Sum(spent_expr)
    )['s'] or Decimal("0.00")
    
    # 2. Витрати за поточний місяць
    start_month = timezone.now().replace(day=1)
    spent_this_month = work_writeoffs_qs(base_qs.filter(date__gte=start_month)).aggregate(
        s=Sum(spent_expr)
    )['s'] or Decimal("0.00")

    # 3. Графік витрат по об'єктах (Top 5)
    wh_stats = work_writeoffs_qs(base_qs).values('warehouse__name').annotate(
        total=Sum(spent_expr)
    ).order_by('-total')[:5]
    
    wh_labels = [x['warehouse__name'] for x in wh_stats]
    wh_data = [float(x['total']) for x in wh_stats]

    # 4. Графік динаміки (останні 6 місяців)
    six_months_ago = timezone.now() - timedelta(days=180)
    trend_stats = work_writeoffs_qs(base_qs.filter(date__gte=six_months_ago)).annotate(
        month=TruncMonth('date')
    ).values('month').annotate(
        total=Sum(spent_expr)
    ).order_by('month')
    
    month_labels = [x['month'].strftime('%Y-%m') for x in trend_stats]
    month_data = [float(x['total']) for x in trend_stats]

    return render(request, 'warehouse/reports.html', {
        'total_spent': total_spent,
        'spent_this_month': spent_this_month,
        'wh_labels': wh_labels,
        'wh_data': wh_data,
        'month_labels': month_labels,
        'month_data': month_data,
    })

# ==============================================================================
# ЗВІТ ПРО СПИСАННЯ (WRITEOFF REPORT)
# ==============================================================================

@staff_required
def writeoff_report(request):
    """
    Звіт по списаннях (Витрати на роботи vs Втрати).
    Виключає переміщення.
    """
    # Базовий QS - тільки реальні списання + фільтр по складах
    qs = restrict_warehouses_qs(Transaction.objects.all(), request.user)
    qs = work_writeoffs_qs(qs.select_related('warehouse', 'material', 'created_by'))
    
    # Фільтрація
    date_from = _parse_date(request.GET.get('date_from'))
    date_to = _parse_date(request.GET.get('date_to'))
    reason = request.GET.get('reason') # OUT or LOSS
    wh_id = request.GET.get('warehouse')

    if date_from: qs = qs.filter(date__gte=date_from)
    if date_to: qs = qs.filter(date__lte=date_to)
    if reason: qs = qs.filter(transaction_type=reason)
    
    if wh_id: 
        # Перевірка доступу до конкретного складу
        allowed_whs = get_allowed_warehouses(request.user)
        if allowed_whs.filter(pk=wh_id).exists():
            qs = qs.filter(warehouse_id=wh_id)
        else:
            # Якщо немає доступу - 404
            raise Http404("Доступ до складу заборонено")
    
    # KPI Stats
    spent_expr = ExpressionWrapper(
        F('quantity') * F('price'),
        output_field=DecimalField(max_digits=14, decimal_places=2)
    )
    
    stats = qs.aggregate(
        work_sum=Sum(spent_expr, filter=Q(transaction_type='OUT')),
        loss_sum=Sum(spent_expr, filter=Q(transaction_type='LOSS'))
    )
    
    # Data list formatting
    report_data = []
    for tx in qs.order_by('-date'):
        # Decimal * Decimal
        total_sum = (tx.quantity * tx.price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        report_data.append({
            'date': tx.date,
            'warehouse': tx.warehouse.name,
            'material': tx.material.name,
            'quantity': tx.quantity,
            'unit': tx.material.unit,
            'price': tx.price,
            'sum': total_sum,
            'type': tx.transaction_type, # OUT or LOSS
            'reason': tx.description,
            'author': tx.created_by.get_full_name() if tx.created_by else 'Система',
            'photo': tx.photo.url if tx.photo else None
        })

    # Склади для фільтру (тільки дозволені)
    warehouses = get_allowed_warehouses(request.user)

    # EXPORT TO EXCEL
    if request.GET.get('export') == 'excel':
        headers = ['Дата', 'Об\'єкт', 'Матеріал', 'Кількість', 'Од.', 'Ціна', 'Сума', 'Тип', 'Причина', 'Автор']
        rows = []
        for row in report_data:
            rows.append([
                row['date'].strftime('%d.%m.%Y') if row['date'] else '',
                row['warehouse'],
                row['material'],
                float(row['quantity']),
                row['unit'],
                float(row['price']),
                float(row['sum']),
                'Роботи' if row['type'] == 'OUT' else 'Втрата',
                row['reason'] or '',
                row['author']
            ])
        filename = f"Writeoff_Report_{timezone.now().strftime('%Y-%m-%d')}.xlsx"
        return create_excel_response(headers, rows, filename, "Списання")

    return render(request, 'warehouse/writeoff_report.html', {
        'report_data': report_data,
        'stats': stats,
        'warehouses': warehouses,
        'f_date_from': date_from,
        'f_date_to': date_to
    })

# ==============================================================================
# ОБОРОТНА ВІДОМІСТЬ (PERIOD REPORT)
# ==============================================================================

@staff_required
def period_report(request):
    """
    Класична оборотка:
    Поч. Залишок + Прихід - Розхід = Кін. Залишок
    Примітка: Тут Розхід включає і переміщення (OUT), щоб баланс сходився.
    """
    form = PeriodReportForm(request.GET or None)
    # Обмежуємо queryset складів у формі
    form.fields['warehouse'].queryset = get_allowed_warehouses(request.user)
    
    report_data = []
    total_value = Decimal("0.00")
    
    if form.is_valid():
        start_date = form.cleaned_data['start_date']
        end_date = form.cleaned_data['end_date']
        warehouse = form.cleaned_data['warehouse']
        category = form.cleaned_data['category']
        
        # Перевірка доступу до складу, якщо він вибраний
        if warehouse:
            enforce_warehouse_access_or_404(request.user, warehouse)
        
        # 1. Матеріали (фільтр)
        materials = Material.objects.all().select_related('category')
        if category:
            materials = materials.filter(category=category)
            
        # 2. Транзакції (фільтр)
        # Спочатку фільтруємо по доступу до складів (якщо склад не вибрано, беремо всі дозволені)
        base_qs = restrict_warehouses_qs(Transaction.objects.all(), request.user)
        
        txs = base_qs.filter(date__gte=start_date, date__lte=end_date)
        if warehouse:
            txs = txs.filter(warehouse=warehouse)
            
        # Для розрахунку початкового залишку беремо все ДО start_date
        pre_txs = base_qs.filter(date__lt=start_date)
        if warehouse:
            pre_txs = pre_txs.filter(warehouse=warehouse)
            
        # Батч-агрегація: 2 запити замість 4N
        pre_agg = {}
        for row in pre_txs.values('material_id', 'transaction_type').annotate(s=Sum('quantity')):
            pre_agg[(row['material_id'], row['transaction_type'])] = row['s'] or Decimal("0.000")

        period_agg = {}
        for row in txs.values('material_id', 'transaction_type').annotate(s=Sum('quantity')):
            period_agg[(row['material_id'], row['transaction_type'])] = row['s'] or Decimal("0.000")

        for mat in materials:
            # Початковий залишок
            start_in = pre_agg.get((mat.id, 'IN'), Decimal("0.000"))
            start_out = (pre_agg.get((mat.id, 'OUT'), Decimal("0.000")) +
                         pre_agg.get((mat.id, 'LOSS'), Decimal("0.000")))
            start_balance = start_in - start_out

            # Обороти за період
            period_in = period_agg.get((mat.id, 'IN'), Decimal("0.000"))
            period_out = (period_agg.get((mat.id, 'OUT'), Decimal("0.000")) +
                          period_agg.get((mat.id, 'LOSS'), Decimal("0.000")))

            # Кінцевий
            end_balance = start_balance + period_in - period_out

            if start_balance == 0 and period_in == 0 and period_out == 0:
                continue

            val = (end_balance * mat.current_avg_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_value += val

            report_data.append({
                'material': mat,
                'category': mat.category.name if mat.category else '-',
                'start_balance': start_balance,
                'income': period_in,
                'outcome': period_out,
                'end_balance': end_balance,
                'total_value': val
            })

    # EXPORT TO EXCEL
    if request.GET.get('export') == 'excel' and report_data:
        headers = ['Категорія', 'Матеріал', 'Од.', 'Поч. залишок', 'Прихід', 'Розхід', 'Кін. залишок', 'Сума (грн)']
        rows = []
        for row in report_data:
            rows.append([
                row['category'],
                row['material'].name,
                row['material'].unit,
                float(row['start_balance']),
                float(row['income']),
                float(row['outcome']),
                float(row['end_balance']),
                float(row['total_value'])
            ])
        filename = f"Period_Report_{timezone.now().strftime('%Y-%m-%d')}.xlsx"
        return create_excel_response(headers, rows, filename, "Оборотка")

    return render(request, 'warehouse/period_report.html', {
        'form': form,
        'report_data': report_data,
        'total_value': total_value
    })

# ==============================================================================
# ЗАЛИШКИ НА СКЛАДАХ (STOCK BALANCE)
# ==============================================================================

@staff_required
def stock_balance_report(request):
    """
    Звіт по поточних залишках з можливістю експорту Excel.
    """
    selected_wh_id = request.GET.get('warehouse')
    warehouses = get_allowed_warehouses(request.user)
    
    report_data = []
    total_value_all = Decimal("0.00")
    
    # Якщо вибрано склад, перевіряємо доступ і фільтруємо
    target_warehouses = warehouses
    if selected_wh_id:
        if not warehouses.filter(id=selected_wh_id).exists():
             raise Http404("Склад не знайдено або доступ заборонено.")
        target_warehouses = warehouses.filter(id=selected_wh_id)
    
    # Батч-агрегація: 2 запити замість 2N
    wh_list = list(target_warehouses)
    wh_map = {wh.id: wh for wh in wh_list}
    multi_balance = get_multi_warehouse_balance(wh_list)

    for wh_id, balance_map in multi_balance.items():
        wh = wh_map.get(wh_id)
        if not wh:
            continue
        for mat, qty in balance_map.items():
            if qty <= 0:
                continue

            sum_val = (qty * mat.current_avg_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_value_all += sum_val

            status = 'ok'
            limit = getattr(mat, 'min_limit', None) or getattr(mat, 'min_stock', None)
            if limit and qty < limit:
                status = 'critical'

            report_data.append({
                'warehouse': wh.name,
                'material': mat.name,
                'characteristics': mat.characteristics,
                'unit': mat.unit,
                'quantity': qty,
                'avg_price': mat.current_avg_price,
                'total_sum': sum_val,
                'status': status
            })

    # EXPORT TO EXCEL
    if request.GET.get('export') == 'excel':
        headers = ['Склад', 'Матеріал', 'Характеристики', 'Од.', 'Кількість', 'Ціна', 'Сума']
        rows = [
            [
                item['warehouse'], item['material'], item['characteristics'],
                item['unit'], item['quantity'],
                float(item['avg_price']), float(item['total_sum']),
            ]
            for item in report_data
        ]
        filename = f"Stock_Balance_{timezone.now().strftime('%Y-%m-%d')}.xlsx"
        return create_excel_response(headers, rows, filename, sheet_title="Залишки")

    return render(request, 'warehouse/stock_balance_report.html', {
        'report_data': report_data,
        'total_value': total_value_all,
        'warehouses': warehouses,
        'selected_wh': int(selected_wh_id) if selected_wh_id else None
    })

# ==============================================================================
# ЖУРНАЛ ПЕРЕМІЩЕНЬ (TRANSFER JOURNAL)
# ==============================================================================

@staff_required
def transfer_journal(request):
    """
    Журнал переміщень. 
    Групує IN/OUT транзакції по transfer_group_id.
    """
    # Фільтр дат
    date_from = _parse_date(request.GET.get('date_from'))
    date_to = _parse_date(request.GET.get('date_to'))

    # Фільтруємо транзакції по доступу (тільки склади юзера)
    qs = restrict_warehouses_qs(Transaction.objects.all(), request.user)

    if date_from: qs = qs.filter(date__gte=date_from)
    if date_to: qs = qs.filter(date__lte=date_to)

    # Використовуємо enrich_transfers для групування
    journal = enrich_transfers(qs)

    return render(request, 'warehouse/transfer_journal.html', {
        'transfers': journal,
        'f_date_from': date_from,
        'f_date_to': date_to
    })

@staff_required
def transfer_analytics(request):
    """
    Аналітика переміщень (Графіки: що везуть, куди везуть).
    """
    # Беремо тільки трансфери (OUT, який має групу)
    # Фільтруємо по доступу до складів
    base_qs = restrict_warehouses_qs(Transaction.objects.all(), request.user)
    qs = base_qs.filter(
        transaction_type='OUT', 
        transfer_group_id__isnull=False
    )
    
    date_from = _parse_date(request.GET.get('date_from'))
    date_to = _parse_date(request.GET.get('date_to'))
    if date_from: qs = qs.filter(date__gte=date_from)
    if date_to: qs = qs.filter(date__lte=date_to)

    # 1. Топ матеріалів (Pie)
    mat_stats = qs.values('material__name').annotate(c=Count('id')).order_by('-c')[:5]
    mat_labels = [x['material__name'] for x in mat_stats]
    mat_data = [x['c'] for x in mat_stats]
    
    # 2. Топ маршрутів (Source -> Destination)
    # Складно зробити одним запитом, бо Destination в іншій транзакції.
    # Спрощення: аналізуємо "Звідки" (Source Warehouse)
    route_stats = qs.values('warehouse__name').annotate(c=Count('id')).order_by('-c')[:5]
    route_labels = [f"З: {x['warehouse__name']}" for x in route_stats]
    route_data = [x['c'] for x in route_stats]
    
    return render(request, 'warehouse/transfer_analytics.html', {
        'total_transfers': qs.count(),
        'mat_labels': mat_labels,
        'mat_data': mat_data,
        'route_labels': route_labels,
        'route_data': route_data,
        'date_from': date_from,
        'date_to': date_to
    })

# ==============================================================================
# ІНШІ ЗВІТИ (SAVINGS, PROBLEMS, HISTORY, AUDIT)
# ==============================================================================

@staff_required
def savings_report(request):
    """
    Звіт про економію. 
    Порівнює ціну закупівлі з ринковою (якщо задана).
    """
    # Тільки IN транзакції (Закупівлі), де є order
    # Фільтруємо по доступу
    base_qs = restrict_warehouses_qs(Transaction.objects.all(), request.user)
    qs = base_qs.filter(transaction_type='IN', order__isnull=False)
    
    date_from = _parse_date(request.GET.get('date_from'))
    date_to = _parse_date(request.GET.get('date_to'))
    if date_from: qs = qs.filter(date__gte=date_from)
    if date_to: qs = qs.filter(date__lte=date_to)

    data = []
    total_saved = Decimal("0.00")
    
    for tx in qs.select_related('material', 'order'):
        market_price = tx.material.current_avg_price # Припустимо, це ринкова
        # Або якщо є окреме поле market_price, використати його.
        # Для прикладу беремо різницю між current_avg (до транзакції) і ціною покупки.
        
        diff = market_price - tx.price
        saving = diff * tx.quantity
        
        if saving != 0:
            total_saved += saving
            data.append({
                'date': tx.date,
                'material': tx.material.name,
                'quantity': tx.quantity,
                'price': tx.price,
                'market_price': market_price,
                'diff': diff,
                'saving': saving
            })
            
    return render(request, 'warehouse/savings_report.html', {
        'report_data': data,
        'total_saved': total_saved,
        'date_from': date_from,
        'date_to': date_to
    })

@staff_required
def problem_areas(request):
    """
    Проблемні зони: Прострочені заявки та Втрати (LOSS).
    """
    # Прострочені
    # Фільтруємо Order по warehouse__in=allowed
    base_order_qs = restrict_warehouses_qs(Order.objects.all(), request.user, warehouse_field='warehouse')
    
    overdue = base_order_qs.filter(
        status__in=['purchasing', 'transit'],
        expected_date__lt=timezone.now().date()
    )
    
    # Втрати
    # Фільтруємо Transaction по warehouse__in=allowed
    base_tx_qs = restrict_warehouses_qs(Transaction.objects.all(), request.user)
    losses = work_writeoffs_qs(base_tx_qs.filter(transaction_type='LOSS')).order_by('-date')[:10]
    
    return render(request, 'warehouse/problem_areas.html', {
        'overdue': overdue,
        'recent_losses': losses,
        'today': timezone.now().date(),
    })

@staff_required
def movement_history(request):
    """
    Загальна історія руху матеріалів.
    """
    # Фільтруємо транзакції
    qs = restrict_warehouses_qs(Transaction.objects.all(), request.user)
    qs = qs.select_related('warehouse', 'material', 'created_by').order_by('-date', '-created_at')
    
    date_from = _parse_date(request.GET.get('date_from'))
    date_to = _parse_date(request.GET.get('date_to'))
    mat_id = request.GET.get('material')

    if date_from: qs = qs.filter(date__gte=date_from)
    if date_to: qs = qs.filter(date__lte=date_to)
    if mat_id: qs = qs.filter(material_id=mat_id)
    
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'warehouse/movement_history.html', {
        'history': page_obj,
        'f_date_from': date_from,
        'f_date_to': date_to
    })

@staff_required
def procurement_journal(request):
    """Журнал закупівель (на основі Orders)"""
    base_qs = restrict_warehouses_qs(Order.objects.all(), request.user)
    orders_qs = base_qs.filter(status='completed').select_related('warehouse', 'created_by').prefetch_related('items__material', 'items__supplier').order_by('-updated_at')
    paginator = Paginator(orders_qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'warehouse/procurement_journal.html', {'orders': page_obj})

@staff_required
def objects_comparison(request):
    """Порівняння бюджетів об'єктів"""
    # Тільки дозволені склади
    warehouses = get_allowed_warehouses(request.user)
    data = []
    
    # Вираз для вартості
    spent_expr = ExpressionWrapper(
        F('quantity') * F('price'),
        output_field=DecimalField(max_digits=14, decimal_places=2)
    )

    for wh in warehouses:
        # Використовуємо work_writeoffs_qs, щоб рахувати тільки РЕАЛЬНІ витрати, а не переміщення
        # Тут не треба restrict_warehouses_qs, бо ми вже ітеруємось по дозволених складах
        spent = work_writeoffs_qs(Transaction.objects.filter(warehouse=wh)).aggregate(s=Sum(spent_expr))['s'] or Decimal("0.00")
        
        data.append({
            'name': wh.name,
            'budget': wh.budget_limit,
            'spent': spent,
            'percent': (spent / wh.budget_limit * 100) if wh.budget_limit > 0 else 0
        })
        
    return render(request, 'warehouse/objects_comparison.html', {'data': data})

@staff_required
def global_audit_log(request):
    if not request.user.is_superuser:
        raise PermissionDenied("Тільки суперадміністратори можуть переглядати журнал аудиту.")
    
    logs = AuditLog.objects.all().select_related('user').order_by('-timestamp')
    
    f_user = request.GET.get('user')
    f_action = request.GET.get('action')
    
    if f_user:
        logs = logs.filter(user__username__icontains=f_user)
    if f_action:
        logs = logs.filter(action_type=f_action)
        
    action_types = AuditLog.ACTION_TYPES if hasattr(AuditLog, 'ACTION_TYPES') else []
        
    paginator = Paginator(logs, 50)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'warehouse/audit_log.html', {
        'logs': page_obj,
        'action_types': action_types
    })

# ==============================================================================
# ПЛАНУВАННЯ (PLANNING REPORT)
# ==============================================================================

@staff_required
def planning_report(request):
    """
    Звіт: План закупівель (на основі активних заявок).
    """
    date_from = _parse_date(request.GET.get('date_from'))
    date_to = _parse_date(request.GET.get('date_to'))
    f_priority = request.GET.get('priority')

    # Вибираємо активні заявки (які ще не виконані і не відхилені)
    # Статуси: new, approved, purchasing
    # Фільтруємо по доступу
    base_qs = restrict_warehouses_qs(Order.objects.all(), request.user)

    qs = base_qs.filter(status__in=['new', 'approved', 'purchasing']).select_related('created_by', 'warehouse').order_by('expected_date')

    if date_from:
        qs = qs.filter(expected_date__gte=date_from)
    if date_to:
        qs = qs.filter(expected_date__lte=date_to)
    if f_priority:
        qs = qs.filter(priority=f_priority)
        
    report_data = []
    
    status_colors = {
        'new': 'primary',       # Синій
        'approved': 'success',  # Зелений
        'purchasing': 'warning',# Жовтий
        'transit': 'info',      # Блакитний
        'completed': 'secondary',
        'rejected': 'danger',
        'draft': 'light'
    }

    for order in qs:
        report_data.append({
            'order': order,
            'responsible': order.created_by.get_full_name() if order.created_by else "Система",
            'status_label': order.get_status_display(),
            'status_color': status_colors.get(order.status, 'secondary'),
            'date_needed': order.expected_date
        })

    # EXPORT TO EXCEL
    if request.GET.get('export') == 'excel' and report_data:
        headers = ['Дата потреби', 'Заявка #', 'Об\'єкт', 'Пріоритет', 'Відповідальний', 'Статус']
        rows = []
        for row in report_data:
            rows.append([
                row['date_needed'].strftime('%d.%m.%Y') if row['date_needed'] else '',
                row['order'].id,
                row['order'].warehouse.name,
                row['order'].get_priority_display(),
                row['responsible'],
                row['status_label']
            ])
        filename = f"Planning_Report_{timezone.now().strftime('%Y-%m-%d')}.xlsx"
        return create_excel_response(headers, rows, filename, "План закупівель")

    return render(request, 'warehouse/planning_report.html', {
        'report_data': report_data,
        'date_from': date_from,
        'date_to': date_to,
        'f_priority': f_priority
    })

# ==============================================================================
# РЕЙТИНГ ПОСТАЧАЛЬНИКІВ (SUPPLIERS RATING)
# ==============================================================================

@staff_required
def suppliers_rating(request):
    """
    Звіт: Рейтинг постачальників (на основі історії закупівель).
    """
    date_from = _parse_date(request.GET.get('date_from'))
    date_to = _parse_date(request.GET.get('date_to'))

    # Тут ми фільтруємо постачальників на основі доступних користувачу замовлень
    # Спочатку дістаємо всі доступні замовлення
    allowed_orders = restrict_warehouses_qs(Order.objects.all(), request.user)

    # Фільтр по датах (за датою створення замовлення)
    if date_from:
        allowed_orders = allowed_orders.filter(created_at__date__gte=date_from)
    if date_to:
        allowed_orders = allowed_orders.filter(created_at__date__lte=date_to)
    
    # Отримуємо всіх постачальників, а кількість замовлень рахуємо тільки по дозволених
    # FIX: Correct backward relation to OrderItem via 'orderitem' and then to Order
    suppliers = Supplier.objects.annotate(
        total_orders=Count(
            'orderitem__order', 
            filter=Q(orderitem__order__in=allowed_orders),
            distinct=True
        )
    ).order_by('-rating', '-total_orders')
    
    report_data = []
    
    for sup in suppliers:
        # Для прикладу: надійність - це просто поле з моделі (0-100)
        # В реальному проекті це може бути складніша формула
        reliability = sup.rating or 80
        
        rel_class = 'success'
        if reliability < 50: rel_class = 'danger'
        elif reliability < 80: rel_class = 'warning'
        
        report_data.append({
            'name': sup.name,
            'contact': f"{sup.contact_person} ({sup.phone})",
            'orders_count': sup.total_orders,
            'reliability': reliability,
            'rel_class': rel_class
        })

    # EXPORT TO EXCEL
    if request.GET.get('export') == 'excel' and report_data:
        headers = ['Назва', 'Контакт', 'Замовлень', 'Надійність (%)']
        rows = []
        for row in report_data:
            rows.append([
                row['name'],
                row['contact'],
                row['orders_count'],
                row['reliability']
            ])
        filename = f"Suppliers_Rating_{timezone.now().strftime('%Y-%m-%d')}.xlsx"
        return create_excel_response(headers, rows, filename, "Постачальники")

    return render(request, 'warehouse/suppliers_rating.html', {
        'report_data': report_data,
        'date_from': date_from,
        'date_to': date_to
    })

# Aliases for compatibility with warehouse/urls.py
stock_balance_view = stock_balance_report
export_stock_report = stock_balance_report