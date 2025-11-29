from django.forms import ModelForm
from .models import (
    Customer, Product, UserProfile,
    InventoryLog, BookLog, VendorPurchase
)


class CustomerForm(ModelForm):
     class Meta:
         model = Customer
         fields = ['customer_name', 'customer_address', 'customer_phone', 'customer_gst', 'customer_email']


class ProductForm(ModelForm):
     class Meta:
         model = Product
         fields = ['model_no', 'product_name', 'product_hsn', 'product_gst_percentage', 'product_rate_with_gst', 'product_discount']


class UserProfileForm(ModelForm):
    def __init__(self, *args, **kwargs):
        # first call parent's constructor
        super(UserProfileForm, self).__init__(*args, **kwargs)
        # there's a `fields` property now
        self.fields['business_title'].required = True

    class Meta:
        model = UserProfile
        fields = ['business_title', 'business_address', 'business_email', 'business_phone', 'business_gst', 'business_brand']


class InventoryLogForm(ModelForm):
    class Meta:
        model = InventoryLog
        fields = ['date', 'change', 'change_type', 'description']


class BookLogForm(ModelForm):
    class Meta:
        model = BookLog
        fields = ['date', 'change', 'change_type', 'description']

class VendorPurchaseForm(ModelForm):
    class Meta:
        model = VendorPurchase
        fields = ['vendor_name', 'vendor_address', 'vendor_phone', 'vendor_gst', 'vendor_email']