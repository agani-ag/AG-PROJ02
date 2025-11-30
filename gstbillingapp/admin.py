from django.contrib import admin

# Model imports
from .models import (
    Customer, Invoice, Product, UserProfile, 
    BillingProfile, Inventory, InventoryLog, 
    BookLog, Book, PurchaseLog, VendorPurchase,
    ExpenseTracker, BankDetails
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
admin.site.register(InventoryLog)
admin.site.register(VendorPurchase)
admin.site.register(ExpenseTracker)