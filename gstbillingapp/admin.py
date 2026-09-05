from django.contrib import admin

# Model imports
from .models import (
    Customer, Invoice, Product, UserProfile,
    Inventory, InventoryLog,
    BookLog, Book, PurchaseLog, VendorPurchase,
    ExpenseTracker, BankDetails,
    ProductCategory, Quotation, Asset, ActiveDevice
)

# User Profile
admin.site.register(UserProfile)

# Core Models
admin.site.register(Book)
admin.site.register(Asset)
admin.site.register(BookLog)
admin.site.register(Invoice)
admin.site.register(Product)
admin.site.register(Customer)
admin.site.register(Inventory)
admin.site.register(BankDetails)
admin.site.register(PurchaseLog)
admin.site.register(InventoryLog)
admin.site.register(VendorPurchase)
admin.site.register(ExpenseTracker)
admin.site.register(ProductCategory)


@admin.register(ActiveDevice)
class ActiveDeviceAdmin(admin.ModelAdmin):
    list_display = ('user', 'token', 'user_agent', 'last_seen', 'created_at')
    list_filter = ('last_seen',)
    search_fields = ('user__username', 'token')
    readonly_fields = ('created_at', 'last_seen')

# Quotation with custom admin
@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = ('quotation_number', 'quotation_customer', 'quotation_date', 'status', 'created_by_customer', 'created_at')
    list_filter = ('status', 'created_by_customer', 'quotation_date', 'created_at')
    search_fields = ('quotation_number', 'quotation_customer__customer_name')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'quotation_date'
    ordering = ('-created_at',)
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'quotation_number', 'quotation_date', 'valid_until', 'quotation_customer')
        }),
        ('Status & Tracking', {
            'fields': ('status', 'created_by_customer'),
            'classes': ('wide',),
            'description': 'Update order status for tracking'
        }),
        ('Order Data', {
            'fields': ('quotation_json', 'is_gst', 'customer_details_modified', 'notes'),
            'classes': ('collapse',)
        }),
        ('Conversion Info', {
            'fields': ('converted_invoice', 'converted_at', 'converted_by'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_as_approved']

    def mark_as_approved(self, request, queryset):
        updated = queryset.update(status='APPROVED')
        self.message_user(request, f'{updated} order(s) marked as Approved.')
    mark_as_approved.short_description = "Mark selected orders as Approved"

