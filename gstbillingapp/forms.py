from django.forms import ModelForm
from .models import (
    Customer, Product, UserProfile,
    InventoryLog, Book, BookLog,
    ExpenseTracker, BankDetails, VendorPurchase
)


class CustomerForm(ModelForm):
    class Meta:
        model = Customer
        fields = ['customer_name', 'customer_address', 'customer_phone', 'customer_gst', 'customer_email'
                   , 'customer_latitude', 'customer_longitude', 'bankdetails']

    def __init__(self, *args, **kwargs):
        super(CustomerForm, self).__init__(*args, **kwargs)
        self.fields['bankdetails'].queryset = BankDetails.objects.filter(whom_account=1)

class ProductForm(ModelForm):
     class Meta:
        model = Product
        fields = ['model_no', 'product_name', 'product_hsn', 'product_gst_percentage',
                    'product_rate_with_gst', 'product_discount']


class UserProfileForm(ModelForm):
    def __init__(self, *args, **kwargs):
        # first call parent's constructor
        super(UserProfileForm, self).__init__(*args, **kwargs)
        # there's a `fields` property now
        self.fields['business_title'].required = True

    class Meta:
        model = UserProfile
        fields = ['business_title', 'business_address', 'business_email', 'business_phone',
                  'business_gst', 'business_brand', 'business_latitude', 'business_longitude', 'bankdetails']
    
    def __init__(self, *args, **kwargs):
        super(UserProfileForm, self).__init__(*args, **kwargs)
        self.fields['bankdetails'].queryset = BankDetails.objects.filter(whom_account=0)

class InventoryLogForm(ModelForm):
    class Meta:
        model = InventoryLog
        fields = ['date', 'change', 'change_type', 'description']


class BookLogForm(ModelForm):
    class Meta:
        model = BookLog
        fields = ['date', 'change', 'change_type', 'description']

class BookLogFullForm(ModelForm):
    class Meta:
        model = BookLog
        fields = ['parent_book','date', 'change', 'change_type', 'description']
        
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields['parent_book'].required = True
        self.fields['change_type'].choices = [
            (0, 'Paid'),
            (3, 'Other'),
        ]
        if self.user:
            self.fields['parent_book'].queryset = Book.objects.filter(customer__isnull=False, customer__user=self.user).order_by('customer__customer_name')
        else:
            self.fields['parent_book'].queryset = Book.objects.none()

class VendorPurchaseForm(ModelForm):
    class Meta:
        model = VendorPurchase
        fields = ['vendor_name', 'vendor_address', 'vendor_phone', 'vendor_gst', 'vendor_email'
                  , 'vendor_latitude', 'vendor_longitude', 'bankdetails']
    
    def __init__(self, *args, **kwargs):
        super(VendorPurchaseForm, self).__init__(*args, **kwargs)
        self.fields['bankdetails'].queryset = BankDetails.objects.filter(whom_account=2)

class ExpenseTrackerForm(ModelForm):
    class Meta:
        model = ExpenseTracker
        fields = ['date', 'category', 'amount', 'reference', 'notes']

class BankDetailsForm(ModelForm):
    class Meta:
        model = BankDetails
        fields = ['account_name', 'account_number', 'bank_name', 'branch_name', 'ifsc_code',
                  'upi_id', 'upi_name', 'business_account', 'customer_account', 'vendor_account', 'whom_account']