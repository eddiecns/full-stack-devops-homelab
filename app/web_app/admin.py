from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Profile, Product, Category, Order, OrderItem
from django.db import transaction


# Register Product
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'stock_quantity', 'availability', 'vendor', 'category')
    list_filter = ('availability', 'category', 'vendor')
    search_fields = ('name', 'description')


# Register Category
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'status', 'total_price', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('user__username',)

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        with transaction.atomic():
            super().save_related(request, form, formsets, change)


# Register OrderItem
@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'product', 'quantity')


# Register Profile with vendor ID display
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'get_user_type', 'vendor_id', 'company_name', 'phone', 'mobile')
    list_filter = ('user__user_type',)
    search_fields = ('vendor_id', 'company_name', 'user__username', 'user__email')
    readonly_fields = ('user',)

    def get_user_type(self, obj):
        return obj.user.user_type.upper()

    get_user_type.short_description = 'User Type'

    fieldsets = (
        ('User Information', {
            'fields': ('user', 'vendor_id')
        }),
        ('Personal Details', {
            'fields': ('surname', 'company_name')
        }),
        ('Contact Information', {
            'fields': ('phone', 'mobile')
        }),
        ('Delivery & Payment', {
            'fields': ('delivery_address', 'payment_method')
        }),
    )


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    fields = ('vendor_id', 'surname', 'company_name', 'phone', 'mobile', 'delivery_address', 'payment_method')
    readonly_fields = ('vendor_id',)


class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ('username', 'email', 'user_type', 'get_vendor_id', 'is_staff', 'is_active')
    list_filter = ('user_type', 'is_staff', 'is_active')
    search_fields = ('username', 'email', 'profile__vendor_id')

    fieldsets = (
        (None, {'fields': ('username', 'email', 'password', 'user_type', 'cell')}),
        ('Permissions', {'fields': ('is_staff', 'is_active', 'groups', 'user_permissions')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2', 'user_type', 'cell', 'is_staff', 'is_active')}
         ),
    )
    ordering = ('username',)
    inlines = [ProfileInline]

    def get_vendor_id(self, obj):
        """Display vendor ID in admin list"""
        if obj.user_type == 'vendor':
            try:
                return obj.profile.vendor_id or '❌ Not assigned'
            except Profile.DoesNotExist:
                return '❌ No profile'
        return '—'

    get_vendor_id.short_description = 'Vendor ID'


# Register CustomUser with custom admin
admin.site.register(CustomUser, CustomUserAdmin)