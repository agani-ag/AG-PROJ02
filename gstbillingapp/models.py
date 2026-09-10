# Django imports
from django.db import models
from django.contrib.auth.models import User
from django.contrib.auth.hashers import check_password, make_password

# Python imports
import uuid
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
    business_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    business_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    bankdetails = models.ForeignKey('BankDetails', blank=True, null=True, on_delete=models.SET_NULL)
    # May this business's customer ledgers appear in the customer app (SyncUp)? Set by a
    # platform admin on the console; it doesn't touch the employee app. Existing businesses
    # default ON (only those with mobile-enabled customers are affected at all), while a
    # business created from the console starts OFF (see console_ops.create_business).
    customer_app_enabled = models.BooleanField(default=True)

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


# ======================= Invoice Data models =================================

class Customer(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    customer_name = models.CharField(max_length=200)
    customer_address = models.TextField(max_length=600, blank=True, null=True)
    customer_phone = models.CharField(max_length=14, blank=True, null=True)
    customer_gst = models.CharField(max_length=15, blank=True, null=True)
    customer_email = models.EmailField(blank=True, null=True)
    is_mobile_user = models.BooleanField(default=False)
    customer_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    customer_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    bankdetails = models.ForeignKey('BankDetails', blank=True, null=True, on_delete=models.SET_NULL)
    DAYS = [
        (0, 'SUNDAY'),
        (1, 'MONDAY'),
        (2, 'TUESDAY'),
        (3, 'WEDNESDAY'),
        (4, 'THURSDAY'),
        (5, 'FRIDAY'),
        (6, 'SATURDAY'),
    ]
    collection_day = models.IntegerField(choices=DAYS, default=0)
    customer_place = models.CharField(max_length=25, blank=True, null=True)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, default=25000.00)
    # Bumped to revoke this customer's mobile (/m/) access link without touching others —
    # baked into the signed token (see mobile_auth.py).
    mobile_token_version = models.IntegerField(default=1)

    def save(self, *args, **kwargs):
        if self.customer_name:
            self.customer_name = self.customer_name.upper()
        if self.customer_address:
            self.customer_address = self.customer_address.upper()
        if self.customer_email:
            self.customer_email = self.customer_email.lower()
        if self.customer_gst:
            self.customer_gst = self.customer_gst.upper()
        if self.customer_place:
            self.customer_place = self.customer_place.upper()

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
    # Holds the ORIGINAL invoice_json only — captured once, on the first debug edit,
    # and never overwritten. Restore always brings back the pristine first version.
    invoice_json_backup = models.TextField(blank=True, null=True)
    inventory_reflected = models.BooleanField(default=True)
    books_reflected = models.BooleanField(default=True)
    is_gst = models.BooleanField(default=True)
    # Which staff member this invoice is credited to (local Employee model). Set from
    # the invoice page's "Map to Employee" picker. Replaces the old external mapping.
    assigned_employee = models.ForeignKey(
        'Employee', on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices'
    )
    assigned_employee_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return str(self.invoice_number) + " | " + str(self.invoice_date)


class Quotation(models.Model):
    """
    Quotation Model - Draft invoice that doesn't affect inventory or books.
    Can be converted to Invoice when approved.
    """
    # A lean order lifecycle: an order is placed, approved, then billed. No delivery-
    # tracking stages — the invoice is the end of the line. To decline a mobile order
    # the owner simply deletes it.
    STATUS_CHOICES = [
        ('PENDING', 'Pending Approval'),   # mobile orders land here — need owner approval first
        ('DRAFT', 'Draft'),                # desktop quotations start here (no approval needed)
        ('APPROVED', 'Approved'),          # approved and ready to convert to an invoice
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
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='DRAFT')
    customer_details_modified = models.BooleanField(default=False)  # Track if JSON customer differs from FK customer
    
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
    created_from_cart = models.BooleanField(default=False)  # Checked out from the Quotation Cart page
    # The field-staff member who raised this order on the mobile app, if any.
    order_employee = models.ForeignKey(
        'Employee', on_delete=models.SET_NULL, null=True, blank=True, related_name='orders'
    )
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
    
    @property
    def needs_approval(self):
        """A mobile order still awaiting the owner's approval."""
        return self.status == 'PENDING'

    def can_be_edited(self):
        """Editable while it's a desktop draft or a mobile order under review."""
        return self.status in ['DRAFT', 'PENDING']

    def can_be_converted(self):
        """Convertible once it's a desktop draft or an approved order. A PENDING mobile
        order must be approved first."""
        return self.status in ['DRAFT', 'APPROVED'] and self.converted_invoice is None
    
    def can_be_deleted(self):
        """Check if quotation can be deleted"""
        # Can delete if not converted, or if converted but invoice was deleted
        if self.status == 'CONVERTED' and self.converted_invoice is None:
            return True  # Invoice was deleted, allow deletion
        return self.status != 'CONVERTED'

    @property
    def order_source(self):
        """Where the quotation came from, so desktop staff can tell a mobile order that
        needs verifying from one they raised themselves. Short code:
          'desktop'  — created directly on the desktop (quotation_create).
          'customer' — placed by the customer from the mobile app.
          'employee' — placed by field-staff (for a customer) from the mobile app.
          'app'      — from the app but neither flag set (legacy)."""
        if not self.created_from_cart:
            return 'desktop'
        if self.created_by_customer:
            return 'customer'
        if self.order_employee_id:
            return 'employee'
        return 'app'

    @property
    def order_source_label(self):
        return {
            'desktop': 'Desktop',
            'customer': 'Customer app',
            'employee': 'Employee app',
            'app': 'Mobile app',
        }[self.order_source]

class ProductCategory(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    category_name = models.CharField(max_length=100)
    parent_category = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='subcategories')

    class Meta:
        verbose_name_plural = "Product Categories"
        ordering = ['parent_category__category_name', 'category_name']

    def save(self, *args, **kwargs):
        if self.category_name:
            self.category_name = self.category_name.upper()
        
        super().save(*args, **kwargs)
    
    def is_parent(self):
        """Check if this is a parent category (has no parent)"""
        return self.parent_category is None
    
    def get_full_path(self):
        """Return full category path (e.g., 'ORGANIC > FRUITS')"""
        if self.parent_category:
            return f"{self.parent_category.category_name} > {self.category_name}"
        return self.category_name

    def __str__(self):
        return self.get_full_path()

# Colours the product_colour dropdown always offers, even before any product uses
# one. Merged with the business's own distinct colours in the form / grid / cart.
DEFAULT_PRODUCT_COLOURS = ['WHITE', 'GREY', 'BLACK']


class Product(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    model_no = models.CharField(max_length=200)
    product_name = models.CharField(max_length=50, null=True, blank=True)
    product_hsn = models.CharField(max_length=50, null=True, blank=True)
    product_discount = models.FloatField(default=0)
    product_gst_percentage = models.FloatField(default=18)
    product_rate_with_gst = models.FloatField(default=0)
    product_purchase_rate = models.FloatField(default=0)
    product_division_category = models.CharField(max_length=50, null=True, blank=True)
    product_model_category = models.CharField(max_length=50, null=True, blank=True)
    product_colour = models.CharField(max_length=30, null=True, blank=True)
    product_image_url = models.TextField(max_length=600, blank=True, null=True)
    product_category = models.ForeignKey(ProductCategory, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        unique_together = [['user', 'model_no']]
        indexes = [
            models.Index(fields=['user', 'model_no']),
        ]

    def save(self, *args, **kwargs):
        if self.model_no:
            self.model_no = self.model_no.upper()
        if self.product_name:
            self.product_name = self.product_name.upper()
        if self.product_division_category:
            self.product_division_category = self.product_division_category.upper()
        if self.product_model_category:
            self.product_model_category = self.product_model_category.upper()
        if self.product_colour:
            # Uppercased like the other tags so seeds (WHITE/GREY/BLACK) and typed
            # values dedupe cleanly in the dropdown.
            self.product_colour = self.product_colour.upper()

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

    def save(self, *args, **kwargs):
        if self.createdby:
            self.createdby = self.createdby.upper()
        if self.change:
            # For 'Other' type, keep the sign as is (positive or negative)
            if self.change_type == 3:
                self.change = self.change
            elif self.change_type == 1:
                self.change = -abs(self.change)
            else:                
                self.change = abs(self.change)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.parent_book.customer.customer_name + " | " + str(self.change) + " | " + self.description + " | " + str(self.date)

# ========================= Purchase Data models ====================================
class PurchaseLog(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    vendor = models.ForeignKey("VendorPurchase", null=True, blank=True, on_delete=models.SET_NULL)
    date = models.DateTimeField(default=datetime.now, blank=True, null=True)
    CHANGE_TYPES = [
        (0, 'Paid'),
        (1, 'Purchase'),
        (2, 'Return'),
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



# ======================= Asset Management =================================
class Asset(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True, null=True)
    value = models.DecimalField(max_digits=15, decimal_places=2)
    date = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True, null=True)

    def save(self, *args, **kwargs):
        if self.name:
            self.name = self.name.upper()
        if self.category:
            self.category = self.category.upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.type})" if self.type else self.name

class AssetLog(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='logs')
    date = models.DateTimeField(default=datetime.now)
    CHANGE_TYPES = [
        (0, 'Credit'),
        (1, 'Debit'),
    ]
    change_type = models.IntegerField(choices=CHANGE_TYPES, default=0)
    change = models.DecimalField(max_digits=15, decimal_places=2)
    category = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True, null=True)

    def save(self, *args, **kwargs):
        if self.category:
            self.category = self.category.upper()
        if self.change_type == 1:
            self.change = -abs(self.change)
        else:
            self.change = abs(self.change)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.asset.name} | {self.get_change_type_display()} | {self.change} | {self.date}"

# ======================= Cheque Management =================================
class ChequeLeaf(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    cheque_number = models.CharField(max_length=30, unique=True)
    leaf_number = models.IntegerField(null=True, blank=True)
    bank = models.CharField(max_length=100, null=True, blank=True)
    branch = models.CharField(max_length=100, null=True, blank=True)
    account_number = models.CharField(max_length=50, null=True, blank=True)
    STATUS_CHOICES = [
        ('UNUSED', 'Unused'),
        ('ISSUED', 'Issued'),
        ('PRESENTED', 'Presented'),
        ('CLEARED', 'Cleared'),
        ('BOUNCED', 'Bounced'),
        ('CANCELLED', 'Cancelled'),
        ('STOPPED', 'Stopped'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='UNUSED')
    amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    payee_name = models.CharField(max_length=200, null=True, blank=True)
    issue_date = models.DateField(default=datetime.now)
    clearance_date = models.DateField(default=datetime.now)
    remarks = models.TextField(max_length=500, null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.payee_name:
            self.payee_name = self.payee_name.upper()
        if self.remarks:
            self.remarks = self.remarks.upper()
        if self.bank:
            self.bank = self.bank.upper()
        if self.branch:
            self.branch = self.branch.upper()
        if self.amount:
            self.amount = round(self.amount, 2)
        if self.cheque_number:
            self.cheque_number = self.cheque_number.upper()
        if self.account_number:
            self.account_number = self.account_number.upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Cheque {self.cheque_number}"


# ======================= Mobile Employee =================================
class Employee(models.Model):
    """
    A staff member of ONE business (the business is the owner's User). Each business
    manages its own employees. Used for the mobile employee app (/m/employee/) — the
    employee signs in via a signed token minted by gstbilling (see mobile_auth.py).

    Multi-business reps are a later phase; today an employee maps to a single business.
    """
    # The home business — the person's owner. Salary / admin / active are per-business on
    # EmployeePosting; a home posting is created alongside the employee.
    business = models.ForeignKey(User, on_delete=models.CASCADE, related_name="employees")
    name = models.CharField(max_length=100)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=14, blank=True, null=True)
    address = models.TextField(max_length=600, blank=True, null=True)
    is_active = models.BooleanField(default=True)   # person-level (mobile login) active
    # Bumped to revoke this employee's mobile access link (baked into the signed token).
    token_version = models.IntegerField(default=1)
    # The code another business pastes to add this person as a shared employee.
    share_code = models.CharField(max_length=20, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    @staticmethod
    def _new_share_code():
        return "EMP-" + uuid.uuid4().hex[:6].upper()

    def covered_businesses(self):
        """The businesses this person is posted to (home + shared), still active."""
        ids = list(self.postings.filter(is_active=True).values_list("business_id", flat=True))
        if self.business_id not in ids:
            ids.append(self.business_id)
        return User.objects.filter(id__in=ids).select_related("userprofile")

    def save(self, *args, **kwargs):
        if self.name:
            self.name = self.name.strip().upper()
        if self.email:
            self.email = self.email.strip().lower()
        if self.address:
            self.address = self.address.strip().upper()
        if not self.share_code:
            code = self._new_share_code()
            while Employee.objects.filter(share_code=code).exclude(pk=self.pk).exists():
                code = self._new_share_code()
            self.share_code = code
        super().save(*args, **kwargs)
        # Every person has a home posting at their owning business.
        if not self.postings.filter(is_home=True).exists():
            EmployeePosting.objects.create(
                employee=self, business=self.business, is_home=True, is_active=self.is_active)

    def __str__(self):
        return f"{self.name} @ {self.business.username}"


class EmployeePosting(models.Model):
    """One posting of a person (Employee) to a business — the per-business record that
    carries their salary, admin rights and active status there, and owns that business's
    attendance / salary / incentive for them. `is_home` marks the owning business."""
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="postings")
    business = models.ForeignKey(User, on_delete=models.CASCADE, related_name="employee_postings")
    salary = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    is_admin = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_home = models.BooleanField(default=False)
    # Only when enabled does this posting get the Attendance & Salary module. Off by
    # default — e.g. a commission-only rep isn't on payroll.
    attendance_eligible = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("employee", "business")
        ordering = ["-is_home", "business_id"]

    def __str__(self):
        return f"{self.employee.name} @ {self.business.username}{' (home)' if self.is_home else ''}"


# ============ Employee Attendance / Salary / Incentive =====================
class AttendanceLog(models.Model):
    """One attendance mark per employee per day. Salary: a working day is every calendar day
    EXCEPT Leave; a blank (unmarked) day counts as Absent (unpaid). Paid units = Present 1,
    Half 0.5; Absent and Leave earn nothing. Mark weekly-offs/holidays as Leave to exclude
    them from the working-day divisor."""
    PRESENT, ABSENT, HALF, LEAVE = 0, 1, 2, 3
    STATUS_CHOICES = [
        (PRESENT, "Present"),
        (ABSENT, "Absent"),
        (HALF, "Half-day"),
        (LEAVE, "Leave"),
    ]
    PAY_UNITS = {PRESENT: 1.0, ABSENT: 0.0, HALF: 0.5, LEAVE: 0.0}

    posting = models.ForeignKey("EmployeePosting", on_delete=models.CASCADE, related_name="attendance_logs")
    date = models.DateField()
    status = models.IntegerField(choices=STATUS_CHOICES, default=PRESENT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("posting", "date")
        ordering = ["-date"]

    @property
    def pay_units(self):
        return self.PAY_UNITS.get(self.status, 0.0)

    def __str__(self):
        return f"{self.date} - {self.get_status_display()}"


class SalaryRecord(models.Model):
    """A month's computed salary snapshot for an employee. Per-day rate = base / total_days;
    net = per-day × paid_units (paid days marked Present/Half/Leave); deduction = base − net
    (i.e. the unpaid — absent or unmarked — day-equivalents)."""
    posting = models.ForeignKey("EmployeePosting", on_delete=models.CASCADE, related_name="salary_records")
    month = models.IntegerField()
    year = models.IntegerField()
    base_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_days = models.IntegerField(default=0)
    paid_units = models.DecimalField(max_digits=5, decimal_places=1, default=0)   # present + leave + 0.5×half
    deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)   # attendance deduction (base − earned)
    advances = models.DecimalField(max_digits=12, decimal_places=2, default=0)    # advances paid / deductions (−)
    bonus = models.DecimalField(max_digits=12, decimal_places=2, default=0)       # extra pay (+)
    calculated_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)   # earned − advances + bonus
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("posting", "month", "year")
        ordering = ["-year", "-month"]

    def __str__(self):
        return f"{self.month}/{self.year} - {self.calculated_salary}"


class EmployeeIncentive(models.Model):
    """An ad-hoc incentive / bonus payable to an employee (separate from monthly salary)."""
    posting = models.ForeignKey("EmployeePosting", on_delete=models.CASCADE, related_name="incentives")
    date = models.DateField(default=datetime.now)
    description = models.TextField(blank=True, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    is_paid = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.amount}"


class ActiveDevice(models.Model):
    """One live login of a user on a device/browser, for the real-time active-device count.

    The browser sends a periodic heartbeat (see views/presence.py) that refreshes
    ``last_seen``. A device is counted as "active" while its last_seen is within the
    presence window; browser-close / logout removes or lets the row go stale so the
    count drops. ``token`` is a client-generated id kept in the browser's localStorage,
    so all tabs of one browser share a token and count as a single device."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="active_devices")
    token = models.CharField(max_length=64)
    user_agent = models.CharField(max_length=300, blank=True, default="")
    last_seen = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "token")
        ordering = ["-last_seen"]

    def __str__(self):
        return f"{self.user} · {self.token[:8]}"


# ======================= Platform (GSTSync operators) =====================
class PlatformAdmin(models.Model):
    """An operator of GSTSync itself — NOT a business on it.

    Completely standalone: its own username and password columns, with NO link to
    auth.User. A platform admin therefore has no row in auth_user at all — it cannot be
    given a UserProfile by accident, cannot appear in the business list, and cannot sign
    in at the business login even in principle. The two populations are disjoint by
    construction rather than by a filter someone might forget.

    `password` stores a Django password HASH, never the password itself. Use
    set_password() / check_password(), which delegate to django.contrib.auth.hashers
    (PBKDF2 by default), so the storage format is Django's and upgrades with Django —
    only the table is ours. (Customer logins are not stored here at all: SyncUp holds
    their password hashes — see Party.)

    Because the usernames live in a different table from business logins, a platform
    admin and a business may share a username without colliding; they are resolved on
    different login screens.
    """
    username = models.CharField(max_length=150, unique=True)
    password = models.CharField(max_length=128)      # HASH — never the raw password
    full_name = models.CharField(max_length=100, blank=True, null=True)
    # Cleared to revoke access without deleting the row (keeps the audit trail of who
    # created which business).
    is_active = models.BooleanField(default=True)
    # Who created this admin. Null for the first one, which is bootstrapped from the
    # command line by someone with server access.
    created_by = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='created_admins')
    created_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    last_login_ip = models.CharField(max_length=45, blank=True, null=True)   # 45 = IPv6

    class Meta:
        ordering = ["full_name", "username"]

    def set_password(self, raw_password):
        """Hash and store. The caller keeps the raw password only long enough to show it."""
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)

    @property
    def initials(self):
        """Always TWO letters for the console avatar.

        "Ganesh S" -> GS (first letter of the first and last words); a single word like
        "ag" -> AG (its first two characters). A one-character name is doubled rather
        than left as a lonely letter, so the avatar is never visually half-empty.
        """
        parts = (self.full_name or self.username or "").split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        if parts:
            word = parts[0]
            return (word[:2] if len(word) >= 2 else word * 2).upper()
        return "??"

    def __str__(self):
        return self.full_name or self.username


# ======================= Shared customers (one real shop owner) ============================
class Party(models.Model):
    """One real shop owner, as decided by a platform admin on the console.

    Every business keeps its own Customer row, so a shop owner who buys from three of our
    businesses exists as three rows. A Party is the admin's statement that those rows are
    one person. It is never created or extended automatically: shared phone numbers and
    GSTINs are only offered to the admin as suggestions (see parties.py).

    A Party may span any number of businesses and GSTINs - one owner can run several firms,
    and a customer can register a GSTIN later without their identity changing.

    The Party also holds the owner's single customer-app login. SyncUp (AG-PROJ01) stores
    the password hash and performs the login; here we keep only its state.
    """
    LOGIN_NONE, LOGIN_ACTIVE, LOGIN_INACTIVE = "none", "active", "inactive"
    LOGIN_STATUS = [
        (LOGIN_NONE, "No login"),
        (LOGIN_ACTIVE, "Active"),
        (LOGIN_INACTIVE, "Deactivated"),
    ]

    name = models.CharField(max_length=200)
    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey("PlatformAdmin", null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="parties_created")
    created_at = models.DateTimeField(auto_now_add=True)

    # ---- customer-app login ----
    # The admin's decision. Whether the login actually works also needs at least one
    # visible ledger - see parties.visible_rows().
    login_status = models.CharField(max_length=10, choices=LOGIN_STATUS, default=LOGIN_NONE)
    login_issued_at = models.DateTimeField(null=True, blank=True)
    # Baked into the /m/ link. Bumped on re-issue and on deactivation, so an old or copied
    # link stops working.
    token_version = models.IntegerField(default=1)
    # What SyncUp was last told about is_active (None = never told). Lets a change that
    # doesn't alter it skip the network call entirely.
    syncup_active = models.BooleanField(null=True, blank=True)
    syncup_synced_at = models.DateTimeField(null=True, blank=True)
    # The last failed push, shown on the console with a retry. Empty when in sync.
    syncup_error = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["name", "id"]

    @property
    def external_id(self):
        """How GSTSync addresses this login in SyncUp's Partner API."""
        return "party-%d" % self.id

    @property
    def login_email(self):
        """The login-only email, gsp{id}@<login domain> (SyncUp lower-cases it; never
        mailed). The domain is set under Console -> Settings and locks once any login
        exists."""
        return self.login_email_at(SyncUpSettings.load().login_domain)

    def login_email_at(self, domain):
        """login_email for a domain already loaded - lists use it to avoid a query per row."""
        return "gsp%d@%s" % (self.id, domain)

    @property
    def has_login(self):
        return self.login_status != self.LOGIN_NONE

    def __str__(self):
        return self.name


class PartyMapping(models.Model):
    """A platform admin's decision that one customer row belongs to a Party.

    Kept in its own table rather than as a column on Customer: business-owned tables stay
    untouched, the row records who decided and on what evidence, and the one-to-one link
    makes it impossible for a customer row to belong to two people.
    """
    EVIDENCE = [
        ("phone_gstin", "Phone and GSTIN"),
        ("phone", "Phone"),
        ("gstin", "GSTIN"),
        ("manual", "Manual"),
    ]

    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="mappings")
    customer = models.OneToOneField("Customer", on_delete=models.CASCADE,
                                    related_name="party_mapping")
    evidence = models.CharField(max_length=12, choices=EVIDENCE, default="manual")
    note = models.CharField(max_length=200, blank=True, default="")
    mapped_by = models.ForeignKey("PlatformAdmin", null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="+")
    mapped_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["party_id", "customer__user_id"]

    def __str__(self):
        return "%s -> %s" % (self.customer_id, self.party_id)


class SyncUpSettings(models.Model):
    """How GSTSync reaches SyncUp (AG-PROJ01) - one row, edited under Console -> Settings.

    In the database rather than settings.py so a platform admin can set SyncUp up, rotate
    the key or move hosts without server access or a restart. load() returns unsaved
    defaults until the screen is first saved, so no data migration is needed (migrations
    are gitignored and generated on each server).

    The partner key has to be sent verbatim as the Bearer token, so unlike a password it
    can't be hashed. It's stored as entered and treated as write-only: the console never
    renders it back, only its last four characters.
    """
    # SyncUp's site, without /partner/v1 (the client adds it).
    api_base = models.CharField(max_length=200, blank=True, default="")
    partner_key = models.CharField(max_length=200, blank=True, default="")
    # This site's public https:// address; the customer's app link is built from it.
    link_base = models.CharField(max_length=200, blank=True, default="")
    timeout = models.PositiveSmallIntegerField(default=5)          # seconds per call
    # Customer logins are gsp{party id}@<this>. Login only - never mailed.
    login_domain = models.CharField(max_length=100, default="gstsync.app")
    updated_by = models.ForeignKey("PlatformAdmin", null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "SyncUp settings"
        verbose_name_plural = "SyncUp settings"

    def save(self, *args, **kwargs):
        self.pk = 1                                 # always the one row
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        return cls.objects.filter(pk=1).first() or cls(pk=1)

    @property
    def is_configured(self):
        return bool(self.api_base and self.partner_key)

    @property
    def key_hint(self):
        return ("\u2022\u2022\u2022\u2022" + self.partner_key[-4:]) if self.partner_key else ""

    def __str__(self):
        return "SyncUp settings"
