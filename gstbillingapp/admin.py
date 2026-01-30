from django.contrib import admin

# Model imports
from .models import (
    Customer, Invoice, Product, UserProfile, 
    BillingProfile, Inventory, InventoryLog, 
    BookLog, Book, PurchaseLog, VendorPurchase,
    ExpenseTracker, BankDetails, Notification,
    ProductCategory, Quotation
)

# User and Billing Profile
admin.site.register(UserProfile)
admin.site.register(BillingProfile)

# Core Models
admin.site.register(Book)
admin.site.register(BookLog)
admin.site.register(Invoice)
admin.site.register(Product)
admin.site.register(Customer)
admin.site.register(Inventory)
admin.site.register(Quotation)
admin.site.register(PurchaseLog)
admin.site.register(BankDetails)
admin.site.register(InventoryLog)
admin.site.register(VendorPurchase)
admin.site.register(ExpenseTracker)
admin.site.register(ProductCategory)

# Notification System
@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'notification_type', 'title', 'is_read', 'is_deleted', 'created_at')
    list_filter = ('notification_type', 'is_read', 'is_deleted', 'created_at')
    search_fields = ('title', 'message', 'user__username')
    readonly_fields = ('created_at', 'read_at')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)