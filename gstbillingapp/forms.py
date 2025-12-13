from django.forms import ModelForm
from django import forms
from .models import (
    Customer, Product, UserProfile,
    InventoryLog, BookLog, VendorPurchase,
    ExpenseTracker, BankDetails, PurchaseInvoice, GSTReturn
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


# ========================= GST Filing Forms ====================================

class PurchaseInvoiceForm(ModelForm):
    """Form for adding/editing purchase invoices"""
    class Meta:
        model = PurchaseInvoice
        fields = [
            'vendor', 'invoice_number', 'invoice_date', 'place_of_supply',
            'taxable_amount', 'cgst_amount', 'sgst_amount', 'igst_amount', 
            'cess_amount', 'total_amount', 'itc_claimed', 'notes'
        ]
        widgets = {
            'invoice_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super(PurchaseInvoiceForm, self).__init__(*args, **kwargs)
        if user:
            self.fields['vendor'].queryset = VendorPurchase.objects.filter(user=user)
        
        # Make fields required
        self.fields['vendor'].required = True
        self.fields['invoice_number'].required = True
        self.fields['invoice_date'].required = True
        self.fields['taxable_amount'].required = True
        self.fields['total_amount'].required = True
    
    def clean(self):
        cleaned_data = super().clean()
        taxable = cleaned_data.get('taxable_amount', 0)
        cgst = cleaned_data.get('cgst_amount', 0)
        sgst = cleaned_data.get('sgst_amount', 0)
        igst = cleaned_data.get('igst_amount', 0)
        cess = cleaned_data.get('cess_amount', 0)
        total = cleaned_data.get('total_amount', 0)
        
        # Validate total amount
        calculated_total = taxable + cgst + sgst + igst + cess
        if abs(float(total) - float(calculated_total)) > 0.01:
            raise forms.ValidationError(
                f"Total amount ({total}) doesn't match calculated total ({calculated_total})"
            )
        
        return cleaned_data


class GSTReturnFilterForm(forms.Form):
    """Form for filtering GST returns by period"""
    month = forms.ChoiceField(
        choices=[(i, f"{i:02d}") for i in range(1, 13)],
        required=True
    )
    year = forms.ChoiceField(
        choices=[(y, str(y)) for y in range(2017, 2030)],
        required=True
    )
    return_type = forms.ChoiceField(
        choices=[('', 'All')] + GSTReturn.RETURN_TYPES,
        required=False
    )