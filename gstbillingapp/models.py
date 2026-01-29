# Django imports
from django.db import models
from django.contrib.auth.models import User

# Python imports
from datetime import datetime
from django.db.models import Q
from django.core.exceptions import ValidationError

# ========================== SAAS Data models ==================================

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    business_title = models.CharField(max_length=100, blank=True, null=True)
    business_address = models.TextField(max_length=400, blank=True, null=True)
    business_email = models.EmailField(blank=True, null=True)
    business_phone = models.CharField(max_length=20, blank=True, null=True)
    business_gst = models.CharField(max_length=15, blank=True, null=True)
    business_brand = models.CharField(max_length=30, blank=True, null=True, default=None)
    business_config = models.TextField(blank=True, null=True, default=None)
    business_uid = models.TextField(blank=True, null=True)
    business_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    business_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    bankdetails = models.ForeignKey('BankDetails', blank=True, null=True, on_delete=models.SET_NULL)

    def save(self, *args, **kwargs):
        if self.business_title:
            self.business_title = self.business_title.upper()
        if self.business_address:
            self.business_address = self.business_address.upper()
        if self.business_email:
            self.business_email = self.business_email.lower()
        if self.business_gst:
            self.business_gst = self.business_gst.upper()
        if self.business_brand:
            self.business_brand = self.business_brand.upper()

        super().save(*args, **kwargs)
    
    def get_bank_details(self):
        return BankDetails.objects.filter(whom_account=0, business_account=self)
    
    def __str__(self):
        return self.user.username


class Plan(models.Model):
    plan_name = models.TextField(max_length=20, blank=True, null=True)
    plan_value = models.IntegerField(blank=True, null=True)
    monthly_invoice_limit = models.IntegerField(blank=True, null=True)


class BillingProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    plan = models.ForeignKey(Plan, blank=True, null=True, on_delete=models.SET_NULL)
    plan_start_date = models.DateField(blank=True, null=True)
    plan_end_date = models.DateField(blank=True, null=True)

    def __str__(self):
        return self.user.username

# ======================= Invoice Data models =================================

class Customer(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    customer_name = models.CharField(max_length=200)
    customer_address = models.TextField(max_length=600, blank=True, null=True)
    customer_phone = models.CharField(max_length=14, blank=True, null=True)
    customer_gst = models.CharField(max_length=15, blank=True, null=True)
    customer_email = models.EmailField(blank=True, null=True)
    customer_password = models.CharField(max_length=15, null=True, blank=True)
    customer_userid = models.CharField(max_length=15, null=True, blank=True)
    is_mobile_user = models.BooleanField(default=False)
    customer_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    customer_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    bankdetails = models.ForeignKey('BankDetails', blank=True, null=True, on_delete=models.SET_NULL)

    def save(self, *args, **kwargs):
        if self.customer_name:
            self.customer_name = self.customer_name.upper()
        if self.customer_address:
            self.customer_address = self.customer_address.upper()
        if self.customer_email:
            self.customer_email = self.customer_email.lower()
        if self.customer_gst:
            self.customer_gst = self.customer_gst.upper()

        super().save(*args, **kwargs)
    
    def get_bank_details(self):
        return BankDetails.objects.filter(whom_account=1, customer_account=self)
    
    def __str__(self):
        return self.customer_name


class Invoice(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    invoice_number = models.IntegerField()
    invoice_date = models.DateField()
    invoice_customer = models.ForeignKey(
        'Customer',
        on_delete=models.SET_NULL,
        null=True
    )
    invoice_json = models.TextField()
    inventory_reflected = models.BooleanField(default=True)
    books_reflected = models.BooleanField(default=True)
    is_gst = models.BooleanField(default=True)
    
    def __str__(self):
        return str(self.invoice_number) + " | " + str(self.invoice_date)


class Quotation(models.Model):
    """
    Quotation Model - Draft invoice that doesn't affect inventory or books.
    Can be converted to Invoice when approved.
    """
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('APPROVED', 'Approved'),
        ('CONVERTED', 'Converted to Invoice'),
    ]
    
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    quotation_number = models.IntegerField()
    quotation_date = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    quotation_customer = models.ForeignKey(
        'Customer',
        on_delete=models.SET_NULL,
        null=True,
        related_name='quotations'
    )
    quotation_json = models.TextField()
    is_gst = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    
    # Conversion tracking
    converted_invoice = models.ForeignKey(
        'Invoice',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='source_quotation'
    )
    converted_at = models.DateTimeField(null=True, blank=True)
    converted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='converted_quotations'
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by_customer = models.BooleanField(default=False)  # For customer self-orders
    notes = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['-quotation_date', '-id']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['quotation_customer', 'status']),
            models.Index(fields=['status', 'quotation_date']),
        ]
    
    def __str__(self):
        return f"QT-{self.quotation_number} | {self.quotation_date} | {self.status}"
    
    def can_be_edited(self):
        """Check if quotation can be edited"""
        return self.status != 'CONVERTED'
    
    def can_be_converted(self):
        """Check if quotation can be converted to invoice"""
        return self.status in ['DRAFT', 'APPROVED'] and self.converted_invoice is None


class Product(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    model_no = models.CharField(max_length=200)
    product_name = models.CharField(max_length=50, null=True, blank=True)
    product_hsn = models.CharField(max_length=50, null=True, blank=True)
    product_discount = models.FloatField(default=0)
    product_gst_percentage = models.FloatField(default=18)
    product_rate_with_gst = models.FloatField(default=0)

    def save(self, *args, **kwargs):
        if self.model_no:
            self.model_no = self.model_no.upper()
        if self.product_name:
            self.product_name = self.product_name.upper()
        
        super().save(*args, **kwargs)

    def __str__(self):
        return str(self.model_no)

# ========================= Inventory Data models ====================================
class InventoryLog(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.SET_NULL)
    date = models.DateTimeField(default=datetime.now, blank=True, null=True)
    last_modified = models.DateTimeField(auto_now=True)
    change = models.IntegerField(default=0)
    CHANGE_TYPES = [
        (0, 'Other'),
        (1, 'Purchase'),
        (2, 'Production'),
        (3, 'Return'),
        (4, 'Sales'),
    ]
    change_type = models.IntegerField(choices=CHANGE_TYPES, default=0)

    associated_invoice = models.ForeignKey(Invoice, blank=True, null=True, default=None, on_delete=models.SET_NULL)
    description = models.TextField(max_length=600, blank=True, null=True)

    def __str__(self):
        return self.product.model_no + " | " + str(self.change) + " | " + self.description + " | " + str(self.date)

class Inventory(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.SET_NULL)
    current_stock = models.IntegerField(default=0)
    alert_level = models.IntegerField(default=0)
    last_log = models.ForeignKey(InventoryLog, null=True, blank=True, default=None, on_delete=models.SET_NULL)

    def __str__(self):
        return self.product.model_no

# ========================= Books Data models ======================================

class Book(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.SET_NULL)
    current_balance = models.FloatField(default=0)
    last_log = models.ForeignKey('BookLog', null=True, blank=True, default=None, on_delete=models.SET_NULL)

    def __str__(self):
        return self.customer.customer_name


class BookLog(models.Model):
    parent_book = models.ForeignKey(Book, null=True, blank=True, on_delete=models.CASCADE)
    date = models.DateTimeField(default=datetime.now, blank=True, null=True)
    last_modified = models.DateTimeField(auto_now=True)
    CHANGE_TYPES = [
        (0, 'Paid'),
        (1, 'Purchased Items'),
        (2, 'Returned Items'),
        (3, 'Other'),
        (4, 'Pending'),
    ]
    change_type = models.IntegerField(choices=CHANGE_TYPES, default=0)
    change = models.FloatField(default=0.0)

    associated_invoice = models.ForeignKey(Invoice, blank=True, null=True, default=None, on_delete=models.SET_NULL)
    description = models.TextField(max_length=600, blank=True, null=True)
    createdby = models.CharField(max_length=100, blank=True, null=True, default='SYSTEM')
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.parent_book.customer.customer_name + " | " + str(self.change) + " | " + self.description + " | " + str(self.date)

# ========================= Purchase Data models ====================================
class PurchaseLog(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    vendor = models.ForeignKey("VendorPurchase", null=True, blank=True, on_delete=models.SET_NULL)
    date = models.DateTimeField(default=datetime.now, blank=True, null=True)
    CHANGE_TYPES = [
        (0, 'Purchase'),
        (1, 'Paid'),
        (3, 'Others'),
    ]
    change_type = models.IntegerField(choices=CHANGE_TYPES, default=0)
    change = models.FloatField(default=0.0)
    reference = models.CharField(max_length=100, blank=True, null=True)
    category = models.CharField(max_length=100, blank=True, null=True)

    def save(self, *args, **kwargs):
        if self.reference:
            self.reference = self.reference.upper()
        if self.category:
            self.category = self.category.upper()

        super().save(*args, **kwargs)

    def __str__(self):
        return str(self.date)

class VendorPurchase(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    vendor_name = models.CharField(max_length=200)
    vendor_address = models.TextField(max_length=600, blank=True, null=True)
    vendor_phone = models.CharField(max_length=14, blank=True, null=True)
    vendor_gst = models.CharField(max_length=15, blank=True, null=True)
    vendor_email = models.EmailField(blank=True, null=True)
    vendor_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    vendor_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    bankdetails = models.ForeignKey('BankDetails', blank=True, null=True, on_delete=models.SET_NULL)

    def save(self, *args, **kwargs):
        if self.vendor_name:
            self.vendor_name = self.vendor_name.upper()
        if self.vendor_address:
            self.vendor_address = self.vendor_address.upper()
        if self.vendor_email:
            self.vendor_email = self.vendor_email.lower()
        if self.vendor_gst:
            self.vendor_gst = self.vendor_gst.upper()

        super().save(*args, **kwargs)
    
    def get_bank_details(self):
        return BankDetails.objects.filter(whom_account=2, vendor_account=self)
    
    def __str__(self):
        return self.vendor_name

# ========================= Expense Tracker Data models ====================================
class ExpenseTracker(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    date = models.DateTimeField(default=datetime.now, blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.CharField(max_length=100)
    notes = models.TextField(blank=True, null=True)
    reference = models.CharField(max_length=100)

    def save(self, *args, **kwargs):
        if self.category:
            self.category = self.category.upper()
        if self.reference:
            self.reference = self.reference.upper()
        if self.amount:
            self.amount = abs(round(self.amount, 2))
        super().save(*args, **kwargs)

    def __str__(self):
        return self.reference + " | " + str(self.amount) + " | " + str(self.category)

# ========================= Bank Data models ========================================
class BankDetails(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    account_name = models.CharField(max_length=200)
    account_number = models.CharField(max_length=50)
    bank_name = models.CharField(max_length=100)
    branch_name = models.CharField(max_length=100, blank=True, null=True)
    ifsc_code = models.CharField(max_length=20, blank=True, null=True)
    upi_id = models.CharField(max_length=255, blank=True, null=True)
    upi_name = models.CharField(max_length=255, blank=True, null=True)
    WHOM_ACCOUNT = [
        (0, 'Business'),
        (1, 'Customer'),
        (2, 'Vendor'),
    ]
    whom_account = models.IntegerField(choices=WHOM_ACCOUNT, default=0)
    business_account = models.ForeignKey(UserProfile, blank=True, null=True, on_delete=models.SET_NULL, related_name='bank_details_business')
    customer_account = models.ForeignKey(Customer, blank=True, null=True, on_delete=models.SET_NULL, related_name='bank_details_customer')
    vendor_account = models.ForeignKey(VendorPurchase, blank=True, null=True, on_delete=models.SET_NULL, related_name='bank_details_vendor')

    def save(self, *args, **kwargs):
        if self.account_name:
            self.account_name = self.account_name.upper()
        if self.bank_name:
            self.bank_name = self.bank_name.upper()
        if self.ifsc_code:
            self.ifsc_code = self.ifsc_code.upper()
        if self.upi_id:
            self.upi_id = self.upi_id.lower()
        if self.upi_name:
            self.upi_name = self.upi_name.upper()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.account_number + " - " + self.account_name