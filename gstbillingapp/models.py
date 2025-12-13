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
    # invoice_number = models.IntegerField()
    invoice_number = models.IntegerField(null=True, blank=True, default=None)
    invoice_date = models.DateField()
    invoice_customer = models.ForeignKey(
        'Customer',
        on_delete=models.SET_NULL,
        null=True
    )
    invoice_json = models.TextField()
    inventory_reflected = models.BooleanField(default=True)
    books_reflected = models.BooleanField(default=True)
    non_gst_mode = models.BooleanField(default=False)
    non_gst_invoice_number = models.IntegerField(null=True, blank=True, default=None)
    
    def save(self, *args, **kwargs):
        if self.non_gst_mode:
            self.non_gst_invoice_number = self.invoice_number
            self.invoice_number = None
        
        super().save(*args, **kwargs)
    
    def __str__(self):
        return str(self.invoice_number) + " | " + str(self.invoice_date)


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
        (2, 'Sold Items'),
        (3, 'Returned Items'),
        (4, 'Other'),
    ]
    change_type = models.IntegerField(choices=CHANGE_TYPES, default=0)
    change = models.FloatField(default=0.0)

    associated_invoice = models.ForeignKey(Invoice, blank=True, null=True, default=None, on_delete=models.SET_NULL)
    description = models.TextField(max_length=600, blank=True, null=True)

    def __str__(self):
        return self.parent_book.customer.customer_name + " | " + str(self.change) + " | " + self.description + " | " + str(self.date)

# ========================= Purchase Data models ====================================
class PurchaseLog(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    date = models.DateTimeField(default=datetime.now, blank=True, null=True)
    STATUS_TYPES = [
        (0, 'Open'),
        (1, 'Closed'),
    ]
    status = models.IntegerField(choices=STATUS_TYPES, default=0)
    P_TYPES = [
        (0, 'Purchase'),
        (1, 'Paid'),
    ]
    ptype = models.IntegerField(choices=P_TYPES, default=0)
    vendor = models.ForeignKey("VendorPurchase", null=True, blank=True, on_delete=models.SET_NULL)
    paid_category = models.CharField(max_length=100, blank=True, null=True)
    purchase_category = models.CharField(max_length=100, blank=True, null=True)
    paid_reference = models.CharField(max_length=100, blank=True, null=True)
    purchase_reference = models.CharField(max_length=100, blank=True, null=True)
    amount = models.IntegerField(blank=True, null=True, default=0)

    def save(self, *args, **kwargs):
        if self.purchase_category:
            self.purchase_category = self.purchase_category.upper()
        if self.paid_category:
            self.paid_category = self.paid_category.upper()

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

# ========================= GST Filing & Auditing Models ====================================

class PurchaseInvoice(models.Model):
    """Track purchase invoices for Input Tax Credit (ITC)"""
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    vendor = models.ForeignKey(VendorPurchase, on_delete=models.SET_NULL, null=True, blank=True)
    related_purchase_log = models.ForeignKey(PurchaseLog, on_delete=models.SET_NULL, null=True, blank=True, related_name='gst_invoice')
    invoice_number = models.CharField(max_length=50)
    invoice_date = models.DateField()
    place_of_supply = models.CharField(max_length=50, blank=True, null=True)
    
    # Amount fields
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2)
    cgst_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cess_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_reverse_charge = models.BooleanField(default=False)
    
    # ITC tracking
    itc_claimed = models.BooleanField(default=True)
    itc_cgst = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    itc_sgst = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    itc_igst = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    itc_cess = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Reconciliation
    gstr2a_matched = models.BooleanField(default=False)
    gstr2b_matched = models.BooleanField(default=False)
    
    # Additional details
    invoice_json = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-invoice_date', '-created_at']
        indexes = [
            models.Index(fields=['user', 'invoice_date']),
            models.Index(fields=['vendor', 'invoice_date']),
            models.Index(fields=['related_purchase_log']),
        ]
    
    def save(self, *args, **kwargs):
        # Auto-calculate ITC if claimed
        if self.itc_claimed:
            self.itc_cgst = self.cgst_amount
            self.itc_sgst = self.sgst_amount
            self.itc_igst = self.igst_amount
            self.itc_cess = self.cess_amount
        else:
            self.itc_cgst = 0
            self.itc_sgst = 0
            self.itc_igst = 0
            self.itc_cess = 0
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.invoice_number} - {self.vendor.vendor_name if self.vendor else 'N/A'} - {self.invoice_date}"


class GSTReturn(models.Model):
    """Store GST return filing data"""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    RETURN_TYPES = [
        ('GSTR1', 'GSTR-1 (Outward Supplies)'),
        ('GSTR3B', 'GSTR-3B (Summary Return)'),
        ('GSTR9', 'GSTR-9 (Annual Return)'),
        ('GSTR9C', 'GSTR-9C (Reconciliation Statement)'),
        ('GSTR4', 'GSTR-4 (Composition Dealer)'),
    ]
    return_type = models.CharField(max_length=10, choices=RETURN_TYPES)
    
    # Period details
    period_month = models.IntegerField()  # 1-12
    period_year = models.IntegerField()
    financial_year = models.CharField(max_length=10, blank=True, null=True)  # e.g., "2024-25"
    
    # Filing details
    filing_date = models.DateField(null=True, blank=True)
    
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PREPARED', 'Prepared'),
        ('FILED', 'Filed'),
        ('PENDING', 'Pending'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    
    # Return data
    json_data = models.TextField(blank=True, null=True)  # Store generated JSON
    acknowledgement_number = models.CharField(max_length=50, null=True, blank=True)
    
    # Summary amounts
    total_taxable_value = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_cgst = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_sgst = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_igst = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_cess = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-period_year', '-period_month']
        unique_together = ['user', 'return_type', 'period_month', 'period_year']
        indexes = [
            models.Index(fields=['user', 'return_type', 'status']),
            models.Index(fields=['period_year', 'period_month']),
        ]
    
    def save(self, *args, **kwargs):
        # Auto-calculate financial year
        if self.period_month >= 4:
            self.financial_year = f"{self.period_year}-{str(self.period_year + 1)[-2:]}"
        else:
            self.financial_year = f"{self.period_year - 1}-{str(self.period_year)[-2:]}"
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.return_type} - {self.period_month:02d}/{self.period_year} - {self.status}"


class GSTRReconciliation(models.Model):
    """Track GSTR-2A/2B reconciliation"""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    period_month = models.IntegerField()
    period_year = models.IntegerField()
    
    # Reference to purchase invoice
    purchase_invoice = models.ForeignKey(PurchaseInvoice, on_delete=models.CASCADE, null=True, blank=True)
    
    # Invoice details
    vendor_gstin = models.CharField(max_length=15)
    vendor_name = models.CharField(max_length=200, blank=True, null=True)
    invoice_number = models.CharField(max_length=50)
    invoice_date = models.DateField()
    
    # Amount comparison
    our_taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    our_cgst = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    our_sgst = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    our_igst = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    
    gstr2_taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    gstr2_cgst = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    gstr2_sgst = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    gstr2_igst = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    
    # Reconciliation status
    STATUS_CHOICES = [
        ('MATCHED', 'Matched'),
        ('MISSING_IN_GSTR2', 'Missing in GSTR-2A/2B'),
        ('MISSING_IN_BOOKS', 'Missing in Our Books'),
        ('AMOUNT_MISMATCH', 'Amount Mismatch'),
        ('DATE_MISMATCH', 'Date Mismatch'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='MATCHED')
    remarks = models.TextField(null=True, blank=True)
    
    # Action taken
    action_taken = models.CharField(max_length=100, blank=True, null=True)
    resolved = models.BooleanField(default=False)
    resolved_date = models.DateField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-period_year', '-period_month', 'status']
        indexes = [
            models.Index(fields=['user', 'period_year', 'period_month']),
            models.Index(fields=['vendor_gstin']),
            models.Index(fields=['status', 'resolved']),
        ]
    
    def __str__(self):
        return f"{self.vendor_gstin} - {self.invoice_number} - {self.status}"


class AuditLog(models.Model):
    """Track all changes for audit trail"""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    ACTION_CHOICES = [
        ('CREATE', 'Create'),
        ('UPDATE', 'Update'),
        ('DELETE', 'Delete'),
        ('VIEW', 'View'),
        ('EXPORT', 'Export'),
    ]
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    model_name = models.CharField(max_length=50)
    object_id = models.IntegerField()
    object_repr = models.CharField(max_length=200, blank=True, null=True)
    
    # Change details
    changes = models.TextField(blank=True, null=True)  # JSON of field changes
    previous_values = models.TextField(blank=True, null=True)  # JSON
    new_values = models.TextField(blank=True, null=True)  # JSON
    
    # Request details
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True, null=True)
    
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['model_name', 'object_id']),
            models.Index(fields=['action', 'timestamp']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.action} - {self.model_name} - {self.timestamp}"


# ========================= Return Invoice & Customer Transactions ====================================

class ReturnInvoice(models.Model):
    """Customer return invoice for returned products"""
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    return_invoice_number = models.IntegerField()
    return_date = models.DateField()
    parent_invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='returns')
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    return_items_json = models.TextField()  # JSON with return details
    
    # Return type
    RETURN_TYPES = [
        (0, 'Full Return'),
        (1, 'Partial Return'),
        (2, 'Defective/Damaged'),
        (3, 'Quality Issue'),
        (4, 'Other')
    ]
    return_type = models.IntegerField(choices=RETURN_TYPES, default=1)
    
    # Total amounts
    return_total_amt_without_gst = models.FloatField()
    return_total_amt_sgst = models.FloatField()
    return_total_amt_cgst = models.FloatField()
    return_total_amt_igst = models.FloatField()
    return_total_amt_with_gst = models.FloatField()
    
    # Reflection flags
    inventory_reflected = models.BooleanField(default=False)
    books_reflected = models.BooleanField(default=False)
    
    # Notes
    reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('user', 'return_invoice_number')
        ordering = ['-return_date', '-return_invoice_number']
        indexes = [
            models.Index(fields=['user', 'return_date']),
            models.Index(fields=['parent_invoice']),
            models.Index(fields=['customer']),
        ]
    
    def __str__(self):
        return f"Return #{self.return_invoice_number} - Invoice #{self.parent_invoice.invoice_number}"


class CustomerPayment(models.Model):
    """Customer payment records"""
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    payment_date = models.DateField()
    amount = models.FloatField()
    
    PAYMENT_MODES = [
        (0, 'Cash'),
        (1, 'Cheque'),
        (2, 'Online Transfer'),
        (3, 'UPI'),
        (4, 'Credit Card'),
        (5, 'Debit Card'),
        (6, 'Other')
    ]
    payment_mode = models.IntegerField(choices=PAYMENT_MODES, default=0)
    
    reference_number = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    book_log = models.OneToOneField(BookLog, on_delete=models.CASCADE, null=True, blank=True, related_name='payment_entry')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-payment_date', '-created_at']
        indexes = [
            models.Index(fields=['user', 'payment_date']),
            models.Index(fields=['customer']),
        ]
    
    def __str__(self):
        return f"{self.customer.customer_name} - ₹{self.amount} - {self.payment_date}"
    
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        # Auto-create BookLog on first save
        if is_new and not self.book_log:
            book = Book.objects.get(user=self.user, customer=self.customer)
            book_log = BookLog(
                parent_book=book,
                date=self.payment_date,
                change_type=0,  # 0 = Paid
                change=self.amount,  # POSITIVE (reduces debt)
                description=f"Payment - {self.get_payment_mode_display()}"
            )
            book_log.save()
            
            book.current_balance += self.amount
            book.last_log = book_log
            book.save()
            
            self.book_log = book_log
            super().save(update_fields=['book_log'])


class CustomerDiscount(models.Model):
    """Customer discount/credit note records"""
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    discount_date = models.DateField()
    amount = models.FloatField()
    
    DISCOUNT_TYPES = [
        (0, 'Cash Discount'),
        (1, 'Trade Discount'),
        (2, 'Settlement Discount'),
        (3, 'Promotional Discount'),
        (4, 'Credit Note'),
        (5, 'Other')
    ]
    discount_type = models.IntegerField(choices=DISCOUNT_TYPES, default=0)
    
    reason = models.TextField()
    notes = models.TextField(blank=True)
    book_log = models.OneToOneField(BookLog, on_delete=models.CASCADE, null=True, blank=True, related_name='discount_entry')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-discount_date', '-created_at']
        indexes = [
            models.Index(fields=['user', 'discount_date']),
            models.Index(fields=['customer']),
        ]
    
    def __str__(self):
        return f"{self.customer.customer_name} - ₹{self.amount} Discount - {self.discount_date}"
    
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        # Auto-create BookLog on first save
        if is_new and not self.book_log:
            book = Book.objects.get(user=self.user, customer=self.customer)
            book_log = BookLog(
                parent_book=book,
                date=self.discount_date,
                change_type=4,  # 4 = Other
                change=self.amount,  # POSITIVE (reduces debt)
                description=f"Discount - {self.get_discount_type_display()}"
            )
            book_log.save()
            
            book.current_balance += self.amount
            book.last_log = book_log
            book.save()
            
            self.book_log = book_log
            super().save(update_fields=['book_log'])