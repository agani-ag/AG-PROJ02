from django.contrib import admin

# Model imports
from .models import (
    Customer, Invoice, Product, UserProfile, Employee,
    BillingProfile, Inventory, InventoryLog, 
    BookLog, Book, PurchaseLog, VendorPurchase,
    ExpenseTracker, BankDetails, PurchaseInvoice,
    GSTReturn, GSTRReconciliation, AuditLog
)

# User and Billing Profile
admin.site.register(UserProfile)
admin.site.register(BillingProfile)

# Employee Management
@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('employee_name', 'employee_userid', 'role', 'is_active', 'user_profile', 'date_joined')
    list_filter = ('role', 'is_active', 'date_joined')
    search_fields = ('employee_name', 'employee_userid', 'employee_phone', 'employee_email')
    readonly_fields = ('date_joined', 'last_login')
    fieldsets = (
        ('Basic Information', {
            'fields': ('user_profile', 'employee_name', 'employee_phone', 'employee_email')
        }),
        ('Login Credentials', {
            'fields': ('employee_userid', 'employee_password')
        }),
        ('Role & Status', {
            'fields': ('role', 'is_active', 'date_joined', 'last_login')
        }),
        ('Permissions', {
            'fields': ('can_create_invoice', 'can_delete_invoice', 'can_view_reports', 
                      'can_manage_inventory', 'can_manage_customers')
        }),
    )

# Core Models
admin.site.register(Book)
admin.site.register(BookLog)
admin.site.register(Invoice)
admin.site.register(Product)
admin.site.register(Customer)
admin.site.register(Inventory)
admin.site.register(PurchaseLog)
admin.site.register(BankDetails)
admin.site.register(InventoryLog)
admin.site.register(VendorPurchase)
admin.site.register(ExpenseTracker)

# GST Filing Models
admin.site.register(PurchaseInvoice)
admin.site.register(GSTReturn)
admin.site.register(GSTRReconciliation)
admin.site.register(AuditLog)