from django import forms
from django.contrib.auth.models import User
from django.forms import inlineformset_factory
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db.models import Sum, Case, When, F, DecimalField
from decimal import Decimal
from django.urls import reverse

from .models import (
    Transaction, Order, OrderItem, OrderComment,
    UserProfile, Warehouse, Category, ConstructionStage, Material
)


# ==============================================================================
# FILE UPLOAD VALIDATORS
# ==============================================================================

# Максимальний розмір файлу: 10 MB
MAX_UPLOAD_SIZE_MB = 10
MAX_UPLOAD_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024

# Дозволені розширення для зображень
ALLOWED_IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'webp']

# Дозволені розширення для документів
ALLOWED_DOC_EXTENSIONS = ['pdf', 'jpg', 'jpeg', 'png']


def validate_file_size(file):
    """Валідатор розміру файлу."""
    if file and hasattr(file, 'size'):
        if file.size > MAX_UPLOAD_SIZE:
            raise ValidationError(
                f"Файл занадто великий. Максимальний розмір: {MAX_UPLOAD_SIZE_MB} MB. "
                f"Ваш файл: {file.size / (1024 * 1024):.1f} MB"
            )


def validate_image_file(file):
    """Валідатор для зображень (розмір + розширення + реальний вміст через Pillow)."""
    if file:
        validate_file_size(file)
        # Перевірка розширення
        ext = file.name.split('.')[-1].lower() if '.' in file.name else ''
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            raise ValidationError(
                f"Недозволений тип файлу. Дозволені: {', '.join(ALLOWED_IMAGE_EXTENSIONS)}"
            )
        # Перевірка реального вмісту файлу через Pillow (захист від rename-атак)
        try:
            from PIL import Image
            file.seek(0)
            img = Image.open(file)
            img.verify()
            file.seek(0)
        except Exception:
            raise ValidationError("Файл не є дійсним зображенням або має пошкоджений вміст.")

# ==============================================================================
# 1. ФОРМИ ТРАНЗАКЦІЙ (INVENTORY MOVEMENT)
# ==============================================================================

class TransactionForm(forms.ModelForm):
    """
    Форма для ручного створення транзакцій (Списання, Прихід, Втрати).
    Використовується на сторінці /transaction/add/
    """
    TYPE_CHOICES = [
        ('OUT', '🛠️ Витрата на роботи'),
        ('LOSS', '🗑️ Бій / Псування / Втрата'),
        ('IN', '🟢 Прихід (Коригування/Залишок)'), 
    ]
    
    transaction_type = forms.ChoiceField(
        choices=TYPE_CHOICES, 
        label="Що відбувається?",
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'type-select'})
    )
    
    # Явне визначення поля матеріалу для гарантованого завантаження списку
    material = forms.ModelChoiceField(
        queryset=Material.objects.all().order_by('name'),
        label="Матеріал",
        widget=forms.Select(attrs={'class': 'form-select tom-select'})
    )

    # Використовуємо DecimalField для точності
    quantity = forms.DecimalField(
        min_value=Decimal("0.001"), 
        max_digits=14, 
        decimal_places=3, 
        label="Кількість",
        widget=forms.NumberInput(attrs={'step': '0.001', 'class': 'form-control'})
    )

    class Meta:
        model = Transaction
        fields = ['transaction_type', 'warehouse', 'material', 'quantity', 'description', 'photo']
        widgets = {
            'warehouse': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'rows': 2, 'class': 'form-control', 'placeholder': 'Коментар...'}),
            'photo': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }

    def clean_photo(self):
        """Валідація фото транзакції."""
        photo = self.cleaned_data.get('photo')
        if photo:
            validate_image_file(photo)
        return photo
        
    def clean(self):
        cleaned_data = super().clean()
        t_type = cleaned_data.get('transaction_type')
        qty = cleaned_data.get('quantity')
        material = cleaned_data.get('material')
        warehouse = cleaned_data.get('warehouse')
        
        # Валідація залишків при списанні
        if t_type in ['OUT', 'LOSS'] and qty and material and warehouse:
            in_qty = Transaction.objects.filter(
                material=material, warehouse=warehouse, transaction_type='IN'
            ).aggregate(s=Sum('quantity'))['s'] or Decimal("0")
            
            out_loss_qty = Transaction.objects.filter(
                material=material, warehouse=warehouse, transaction_type__in=['OUT', 'LOSS']
            ).aggregate(s=Sum('quantity'))['s'] or Decimal("0")
            
            current_stock = in_qty - out_loss_qty
            
            if qty > current_stock:
                raise ValidationError(f"Недостатньо товару на складі! Доступно: {current_stock} {material.unit}")
                
        return cleaned_data

# ==============================================================================
# 2. ФОРМИ ЗАЯВОК (ORDERS)
# ==============================================================================

class OrderForm(forms.ModelForm):
    """Форма створення/редагування самої заявки (шапка)"""
    class Meta:
        model = Order
        fields = ['warehouse', 'priority', 'expected_date', 'note', 'request_photo']
        widgets = {
            'warehouse': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'expected_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'note': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'request_photo': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*,.pdf'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        self._form_user = user  # зберігаємо для clean_warehouse
        super().__init__(*args, **kwargs)

        # Для прораба (не staff) - обмежуємо тільки його складами
        if user and not user.is_staff:
            if hasattr(user, 'profile') and user.profile.warehouses.exists():
                self.fields['warehouse'].queryset = user.profile.warehouses.all()
            else:
                # Якщо у прораба немає призначених складів - порожній список
                self.fields['warehouse'].queryset = Warehouse.objects.none()

    def clean_warehouse(self):
        """Явна перевірка доступу до складу (захист від IDOR через підміну POST-параметра)."""
        warehouse = self.cleaned_data.get('warehouse')
        user = self._form_user
        if user and not user.is_staff and warehouse:
            if not hasattr(user, 'profile') or not user.profile.warehouses.filter(pk=warehouse.pk).exists():
                raise ValidationError("У вас немає доступу до цього складу.")
        return warehouse

    def clean_request_photo(self):
        """Валідація фото/документа заявки."""
        photo = self.cleaned_data.get('request_photo')
        if photo:
            validate_file_size(photo)
            ext = photo.name.split('.')[-1].lower() if '.' in photo.name else ''
            if ext not in ALLOWED_DOC_EXTENSIONS:
                raise ValidationError(
                    f"Недозволений тип файлу. Дозволені: {', '.join(ALLOWED_DOC_EXTENSIONS)}"
                )
        return photo

class OrderItemForm(forms.ModelForm):
    """Форма одного рядка заявки (Матеріал + Кількість)"""
    material = forms.ModelChoiceField(
        queryset=Material.objects.all().order_by('name'),
        widget=forms.Select(attrs={'class': 'form-select tom-select'}) # Клас для TomSelect JS
    )
    quantity = forms.DecimalField(
        min_value=Decimal("0.001"), 
        max_digits=14, 
        decimal_places=3, 
        widget=forms.NumberInput(attrs={'step': '0.001', 'class': 'form-control'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Додаємо URL для AJAX пошуку матеріалів
        self.fields['material'].widget.attrs.update({
            'data-ajax-url': reverse('ajax_materials')
        })

    class Meta:
        model = OrderItem
        fields = ['material', 'quantity']

# FormSet для редагування списку товарів у заявці
OrderItemFormSet = inlineformset_factory(
    Order, OrderItem, 
    form=OrderItemForm,
    extra=1, 
    can_delete=True
)

# Alias for backward compatibility (для manager.py, foreman.py та інших старих імпортів)
OrderFnItemFormSet = OrderItemFormSet


class OrderCommentForm(forms.ModelForm):
    """Форма додавання коментаря до заявки"""
    class Meta:
        model = OrderComment
        fields = ['text']
        widgets = {
            'text': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Написати повідомлення...'})
        }

# ==============================================================================
# 3. ФОРМИ ПРОФІЛЮ
# ==============================================================================

class UserUpdateForm(forms.ModelForm):
    """Редагування основних даних користувача (User)"""
    email = forms.EmailField()

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }

class ProfileUpdateForm(forms.ModelForm):
    """Редагування розширених даних профілю (UserProfile)"""
    class Meta:
        model = UserProfile
        fields = ['phone', 'photo', 'position']
        widgets = {
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'position': forms.TextInput(attrs={'class': 'form-control'}),
            'photo': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }

    def clean_photo(self):
        """Валідація фото профілю."""
        photo = self.cleaned_data.get('photo')
        if photo:
            validate_image_file(photo)
        return photo


# ==============================================================================
# 4. ФОРМИ ЗВІТІВ (ФІЛЬТРИ)
# ==============================================================================

class PeriodReportForm(forms.Form):
    """
    Форма фільтрації для оборотної відомості та інших звітів.
    """
    start_date = forms.DateField(
        label="З дати",
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    end_date = forms.DateField(
        label="По дату",
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.all(), 
        required=False, 
        label="Склад",
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label="-- Всі склади --"
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.all(), 
        required=False, 
        label="Категорія",
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label="-- Всі категорії --"
    )