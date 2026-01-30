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
admin.site.register(PurchaseLog)
admin.site.register(BankDetails)

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
    
    actions = ['mark_as_approved', 'mark_as_processing', 'mark_as_packed', 'mark_as_shipped', 'mark_as_out_for_delivery', 'mark_as_delivered']
    
    def mark_as_approved(self, request, queryset):
        updated = queryset.update(status='APPROVED')
        self.message_user(request, f'{updated} order(s) marked as Approved.')
    mark_as_approved.short_description = "Mark selected orders as Approved"
    
    def mark_as_processing(self, request, queryset):
        updated = queryset.update(status='PROCESSING')
        self.message_user(request, f'{updated} order(s) marked as Processing.')
    mark_as_processing.short_description = "Mark selected orders as Processing"
    
    def mark_as_packed(self, request, queryset):
        updated = queryset.update(status='PACKED')
        self.message_user(request, f'{updated} order(s) marked as Packed.')
    mark_as_packed.short_description = "Mark selected orders as Packed"
    
    def mark_as_shipped(self, request, queryset):
        updated = queryset.update(status='SHIPPED')
        self.message_user(request, f'{updated} order(s) marked as Shipped.')
    mark_as_shipped.short_description = "Mark selected orders as Shipped"
    
    def mark_as_out_for_delivery(self, request, queryset):
        updated = queryset.update(status='OUT_FOR_DELIVERY')
        self.message_user(request, f'{updated} order(s) marked as Out for Delivery.')
    mark_as_out_for_delivery.short_description = "Mark selected orders as Out for Delivery"
    
    def mark_as_delivered(self, request, queryset):
        updated = queryset.update(status='DELIVERED')
        self.message_user(request, f'{updated} order(s) marked as Delivered.')
    mark_as_delivered.short_description = "Mark selected orders as Delivered"

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