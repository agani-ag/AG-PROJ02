from django.contrib import admin

# Model imports
from .models import Customer
from .models import Invoice
from .models import Product
from .models import UserProfile
from .models import BillingProfile
from .models import Inventory
from .models import InventoryLog
from .models import BookLog
from .models import Book
from .models import PurchaseLog
from .models import VendorPurchase

# User and Billing Profile
admin.site.register(UserProfile)
admin.site.register(BillingProfile)

# Core Models
admin.site.register(Customer)
admin.site.register(Invoice)
admin.site.register(Product)
admin.site.register(Inventory)
admin.site.register(InventoryLog)
admin.site.register(Book)
admin.site.register(BookLog)
admin.site.register(PurchaseLog)
admin.site.register(VendorPurchase)