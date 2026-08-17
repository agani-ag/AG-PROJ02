from django import forms
from django.forms import ModelForm
from .models import (
    Customer, Product, UserProfile,
    InventoryLog, Book, BookLog,
    ExpenseTracker, BankDetails, VendorPurchase,
    PurchaseLog, ProductCategory, Asset, AssetLog,
    ChequeLeaf, DEFAULT_PRODUCT_COLOURS
)


class CustomerForm(ModelForm):
    class Meta:
        model = Customer
        fields = ['customer_name', 'customer_address', 'customer_phone', 'customer_gst', 'customer_email',
                   'customer_place', 'customer_latitude', 'customer_longitude', 'bankdetails', 'collection_day']
        widgets = {
            'customer_place': forms.TextInput(attrs={'placeholder': 'Enter Collection Place'}),
        }

    def __init__(self, *args, **kwargs):
        super(CustomerForm, self).__init__(*args, **kwargs)
        self.fields['bankdetails'].queryset = BankDetails.objects.filter(whom_account=1)

class ProductForm(ModelForm):
     # These three are free-text "tag" fields. Declared explicitly as CharFields so
     # Django accepts ANY value (typed or selected) with no "Select a valid choice"
     # validation, while still rendering as a <select> so the Select2 tags:true
     # editable dropdown (see product_edit.html) can turn each into a type-or-select box.
     product_division_category = forms.CharField(
         required=False, widget=forms.Select(attrs={'class': 'editable-dropdown'})
     )
     product_model_category = forms.CharField(
         required=False, widget=forms.Select(attrs={'class': 'editable-dropdown'})
     )
     product_colour = forms.CharField(
         required=False, widget=forms.Select(attrs={'class': 'editable-dropdown'})
     )

     class Meta:
        model = Product
        fields = ['model_no', 'product_name', 'product_hsn', 'product_gst_percentage', 'product_purchase_rate',
                    'product_rate_with_gst', 'product_discount', 'product_image_url', 'product_category',
                    'product_division_category', 'product_model_category', 'product_colour']

     def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super(ProductForm, self).__init__(*args, **kwargs)

        # 1. Handle category filtering logic
        if user:
            if 'product_category' in self.fields:
                self.fields['product_category'].queryset = ProductCategory.objects.filter(
                    user=user, parent_category__isnull=False
                ).select_related('parent_category').order_by('parent_category__category_name', 'category_name')
                self.fields['product_category'].label_from_instance = lambda obj: obj.get_full_path()

        # 2. Populate each tag field's <select> options with the business's distinct
        #    values (colour also seeds WHITE/GREY/BLACK). Select2 tags:true then lets
        #    the user pick one or type a brand-new value on top of these.
        base_query = Product.objects.filter(user=user) if user else Product.objects.all()

        for field_name, prompt, seeds in (
            ('product_division_category', 'Select or type a division…', []),
            ('product_model_category', 'Select or type a model category…', []),
            ('product_colour', 'Select or type a colour…', DEFAULT_PRODUCT_COLOURS),
        ):
            distinct = list(seeds)
            for value in (base_query.values_list(field_name, flat=True)
                          .exclude(**{field_name + '__isnull': True})
                          .exclude(**{field_name: ''})
                          .distinct().order_by(field_name)):
                if value not in distinct:
                    distinct.append(value)

            # Ensure the current saved / submitted value is present so it shows selected.
            current = self.data.get(field_name) or getattr(self.instance, field_name, None)
            if current and current not in distinct:
                distinct.insert(0, current)

            self.fields[field_name].widget.choices = (
                [('', prompt)] + [(v, v) for v in distinct]
            )

class UserProfileForm(ModelForm):
    def __init__(self, *args, **kwargs):
        # first call parent's constructor
        super(UserProfileForm, self).__init__(*args, **kwargs)
        # there's a `fields` property now
        self.fields['business_title'].required = True

    class Meta:
        model = UserProfile
        fields = ['business_title', 'business_address', 'business_email', 'business_phone', 'link_to_project1',
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
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['description'].required = True

class BookLogFullForm(ModelForm):
    class Meta:
        model = BookLog
        fields = ['parent_book','date', 'change', 'change_type', 'description','associated_invoice']
        
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields['parent_book'].required = True
        self.fields['description'].required = True
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

class PurchaseLogForm(ModelForm):
    class Meta:
        model = PurchaseLog
        fields = ['date', 'change_type', 'change', 'vendor', 'reference', 'category']

class AssetForm(ModelForm):
    class Meta:
        model = Asset
        fields = ['name', 'category', 'value', 'date', 'description']

class AssetLogForm(ModelForm):
    class Meta:
        model = AssetLog
        fields = ['date', 'change_type', 'change', 'category', 'description']

class ChequeLeafForm(ModelForm):
    class Meta:
        model = ChequeLeaf
        fields = ['cheque_number', 'leaf_number', 'status', 'amount', 'payee_name', 
                  'issue_date', 'clearance_date', 'remarks', 'bank', 'branch', 'account_number']
    
    def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.fields['amount'].required = True