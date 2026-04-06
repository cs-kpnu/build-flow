from .views.utils import get_user_warehouses


def sidebar_warehouses(request):
    """Додає список доступних складів у контекст кожного шаблону."""
    if request.user.is_authenticated:
        warehouses = get_user_warehouses(request.user)
        first_wh = warehouses.first()
        return {
            'sidebar_warehouses': warehouses,
            'first_warehouse': first_wh,
        }
    return {}
