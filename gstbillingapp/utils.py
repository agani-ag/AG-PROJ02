# Django imports
from django.db.models import Sum
from gstbilling import settings
from django.shortcuts import get_object_or_404

# Python imports
import re
import json
import datetime

# Model imports
from .models import (
    Product, VendorPurchase,
    Inventory, InventoryLog,
    Book, BookLog, Customer
)

#  ================= Customer matching ====================
def find_matching_customer(user, data):
    """
    Locate the existing Customer an invoice / quotation form refers to.

    Matches on the normalised name (+ phone when the form supplies one), NOT on an
    exact name+address+phone+GST match. The old exact match compared customer_gst,
    so a non-GST customer — stored with a NULL GST — never equalled the form's empty
    '' GST, and the caller wrongly bounced the user to 'Add Customer' for a customer
    that already existed. Name is upper-cased to line up with Customer.save(), which
    stores it upper-case.

    Shared by quotation_create/edit and invoice_create. Expects the POST field names
    'customer-name' and 'customer-phone'. Returns the Customer or None.
    """
    name = (data.get('customer-name') or '').strip().upper()
    if not name:
        return None

    qs = Customer.objects.filter(user=user, customer_name=name).order_by('id')

    # Prefer a phone match to disambiguate namesakes, but only when it actually
    # narrows things down — a blank or non-matching phone must not lose a valid hit.
    phone = (data.get('customer-phone') or '').strip()
    if phone:
        phone_qs = qs.filter(customer_phone=phone)
        if phone_qs.exists():
            qs = phone_qs

    return qs.first()


#  ================= GST Calculation ====================
def calculate_item_amounts(rate_with_gst, gst_percentage, discount, qty, igstcheck=False):
    """
    Canonical GST math for a single line item — the one convention used everywhere.

    Despite its name, product_rate_with_gst is treated as GST-EXCLUSIVE: the
    discount comes off the rate first, then GST is added on top of the discounted
    rate. This mirrors update_amounts() in static/gstbillingapp/js/main.js, which
    is what the quotation/invoice form posts, so a quotation's total does not move
    when it is converted to an invoice.
    """
    rate_with_gst = float(rate_with_gst or 0)
    gst_percentage = float(gst_percentage or 0)
    discount = float(discount or 0)
    qty = float(qty or 0)

    rate_without_gst = rate_with_gst - (rate_with_gst * discount / 100)
    amt_without_gst = rate_without_gst * qty

    if igstcheck:
        igst = amt_without_gst * gst_percentage / 100
        sgst = cgst = 0.0
    else:
        sgst = cgst = amt_without_gst * gst_percentage / 200
        igst = 0.0

    amt_with_gst = amt_without_gst + sgst + cgst + igst

    return {
        'rate_without_gst': round(rate_without_gst, 2),
        'amt_without_gst': round(amt_without_gst, 2),
        'amt_sgst': round(sgst, 2),
        'amt_cgst': round(cgst, 2),
        'amt_igst': round(igst, 2),
        'amt_with_gst': round(amt_with_gst, 2),
    }


def build_quotation_item(product, qty, igstcheck=False, discount=None):
    """
    Build one quotation_json item from a Product, priced by the canonical rule.

    Rate and GST% are ALWAYS read from the Product — never from the caller — so a
    tampered client payload cannot reprice a line. `discount` may be overridden
    (staff set a per-line discount in the cart); it is clamped to 0-100. Pass
    discount=None to use the product's own discount.

    Emits the same keys invoice_data_processor() produces, so quotations created
    from a cart/order render identically in the invoice printer and viewer.
    """
    if discount is None:
        discount = product.product_discount or 0
    discount = min(100.0, max(0.0, float(discount or 0)))

    amounts = calculate_item_amounts(
        product.product_rate_with_gst,
        product.product_gst_percentage,
        discount,
        qty,
        igstcheck,
    )

    return {
        'invoice_model_no': product.model_no or '',
        'invoice_product': product.product_name or '',
        'invoice_hsn': product.product_hsn or '',
        'invoice_qty': int(qty),
        'invoice_discount': discount,
        'invoice_rate_with_gst': float(product.product_rate_with_gst or 0),
        'invoice_gst_percentage': float(product.product_gst_percentage or 0),
        'invoice_rate_without_gst': amounts['rate_without_gst'],
        'invoice_amt_without_gst': amounts['amt_without_gst'],
        'invoice_amt_sgst': amounts['amt_sgst'],
        'invoice_amt_cgst': amounts['amt_cgst'],
        'invoice_amt_igst': amounts['amt_igst'],
        'invoice_amt_with_gst': amounts['amt_with_gst'],
        # Kept for existing order-history consumers that read invoice_amt.
        'invoice_amt': amounts['amt_with_gst'],
    }


#  ================= Invoice JSON debug-edit ====================

INVOICE_ITEM_INPUT_KEYS = (
    'invoice_model_no', 'invoice_product', 'invoice_hsn',
    'invoice_qty', 'invoice_discount', 'invoice_rate_with_gst',
    'invoice_gst_percentage',
)


def recompute_invoice_data(invoice_data):
    """
    Structurally validate an edited invoice_json dict, then regenerate every
    computed amount from the per-item inputs (qty / rate / discount / gst%),
    honoring igstcheck. The caller's totals are ignored and rebuilt so the saved
    invoice is always internally consistent.

    Mutates and returns the same dict. Raises ValueError with a human-readable
    message on any structural problem — the debug save aborts on that.
    """
    if not isinstance(invoice_data, dict):
        raise ValueError("Invoice JSON must be an object.")

    items = invoice_data.get('items')
    if not isinstance(items, list) or len(items) == 0:
        raise ValueError("Invoice JSON must have a non-empty 'items' list.")

    igstcheck = bool(invoice_data.get('igstcheck', False))

    total_without_gst = total_sgst = total_cgst = total_igst = total_with_gst = 0.0

    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Item {idx} is not an object.")
        for key in INVOICE_ITEM_INPUT_KEYS:
            if key not in item:
                raise ValueError(f"Item {idx} is missing '{key}'.")

        try:
            qty = float(item['invoice_qty'])
            rate = float(item['invoice_rate_with_gst'])
            discount = float(item['invoice_discount'])
            gst = float(item['invoice_gst_percentage'])
        except (TypeError, ValueError):
            raise ValueError(f"Item {idx} has a non-numeric qty / rate / discount / gst.")

        amounts = calculate_item_amounts(rate, gst, discount, qty, igstcheck)

        item['invoice_rate_without_gst'] = amounts['rate_without_gst']
        item['invoice_amt_without_gst'] = amounts['amt_without_gst']
        item['invoice_amt_sgst'] = amounts['amt_sgst']
        item['invoice_amt_cgst'] = amounts['amt_cgst']
        item['invoice_amt_igst'] = amounts['amt_igst']
        item['invoice_amt_with_gst'] = amounts['amt_with_gst']
        # Order-history consumers read invoice_amt; keep it in step.
        item['invoice_amt'] = amounts['amt_with_gst']

        total_without_gst += amounts['amt_without_gst']
        total_sgst += amounts['amt_sgst']
        total_cgst += amounts['amt_cgst']
        total_igst += amounts['amt_igst']
        total_with_gst += amounts['amt_with_gst']

    invoice_data['igstcheck'] = igstcheck
    invoice_data['invoice_total_amt_without_gst'] = round(total_without_gst, 2)
    invoice_data['invoice_total_amt_sgst'] = round(total_sgst, 2)
    invoice_data['invoice_total_amt_cgst'] = round(total_cgst, 2)
    invoice_data['invoice_total_amt_igst'] = round(total_igst, 2)
    invoice_data['invoice_total_amt_with_gst'] = round(total_with_gst, 2)

    return invoice_data


def remove_book_entries_for_invoice(invoice):
    """Delete this invoice's book log(s) and re-total the book — the books half of
    a re-reflect, mirroring remove_inventory_entries_for_invoice()."""
    if invoice.invoice_customer is None:
        return
    book = Book.objects.filter(user=invoice.user, customer=invoice.invoice_customer).first()
    if not book:
        return
    BookLog.objects.filter(parent_book=book, associated_invoice=invoice).delete()
    recalculate_book_current_balance(book)


#  ================= Invoice Methods ====================
def invoice_data_validator(invoice_data):
    
    # Validate Invoice Info ----------

    # invoice-number
    try:
        invoice_number = int(invoice_data['invoice-number'])
    except:
        print("Error: Incorrect Invoice Number")
        return "Error: Incorrect Invoice Number"

    # invoice date
    try:
        date_text = invoice_data['invoice-date']
        datetime.datetime.strptime(date_text, '%Y-%m-%d')
    except:
        print("Error: Incorrect Invoice Date")
        return "Error: Incorrect Invoice Date"

    # Validate Customer Data ---------

    # customer-name
    if len(invoice_data['customer-name']) < 1 or len(invoice_data['customer-name']) > 200:
        print("Error: Incorrect Customer Name")
        return "Error: Incorrect Customer Name"

    if len(invoice_data['customer-address']) > 600:
        print("Error: Incorrect Customer Address")
        return "Error: Incorrect Customer Address"

    if len(invoice_data['customer-phone']) > 14:
        print("Error: Incorrect Customer Phone")
        return "Error: Incorrect Customer Phone"
    if len(invoice_data['customer-gst']) != 15 and len(invoice_data['customer-gst']) != 0:
        print("Error: Incorrect Customer GST")
        return "Error: Incorrect Customer GST"
    return None


def invoice_data_processor(invoice_post_data):
    print(invoice_post_data)
    processed_invoice_data = {}

    processed_invoice_data['invoice_number'] = invoice_post_data['invoice-number']
    processed_invoice_data['invoice_date'] = invoice_post_data['invoice-date']

    processed_invoice_data['customer_name'] = invoice_post_data['customer-name']
    processed_invoice_data['customer_address'] = invoice_post_data['customer-address']
    processed_invoice_data['customer_phone'] = invoice_post_data['customer-phone']
    processed_invoice_data['customer_gst'] = invoice_post_data['customer-gst']

    processed_invoice_data['vehicle_number'] = invoice_post_data['vehicle-number']

    if 'igstcheck' in  invoice_post_data:
        processed_invoice_data['igstcheck'] = True
    else:
        processed_invoice_data['igstcheck'] = False

    processed_invoice_data['items'] = []
    processed_invoice_data['invoice_total_amt_without_gst'] = float(invoice_post_data['invoice-total-amt-without-gst'])
    processed_invoice_data['invoice_total_amt_sgst'] = float(invoice_post_data['invoice-total-amt-sgst'])
    processed_invoice_data['invoice_total_amt_cgst'] = float(invoice_post_data['invoice-total-amt-cgst'])
    processed_invoice_data['invoice_total_amt_igst'] = float(invoice_post_data['invoice-total-amt-igst'])
    processed_invoice_data['invoice_total_amt_with_gst'] = float(invoice_post_data['invoice-total-amt-with-gst'])


    invoice_post_data = dict(invoice_post_data)
    for idx, product in enumerate(invoice_post_data['invoice-model-no']):
        if product:
            print(idx, product)
            item_entry = {}
            item_entry['invoice_model_no'] = product
            item_entry['invoice_product'] = invoice_post_data['invoice-product'][idx]
            item_entry['invoice_hsn'] = invoice_post_data['invoice-hsn'][idx]
            item_entry['invoice_qty'] = int(invoice_post_data['invoice-qty'][idx])
            item_entry['invoice_discount'] = float(invoice_post_data['invoice-discount'][idx])
            item_entry['invoice_rate_with_gst'] = float(invoice_post_data['invoice-rate-with-gst'][idx])
            item_entry['invoice_gst_percentage'] = float(invoice_post_data['invoice-gst-percentage'][idx])

            item_entry['invoice_rate_without_gst'] = float(invoice_post_data['invoice-rate-without-gst'][idx])
            item_entry['invoice_amt_without_gst'] = float(invoice_post_data['invoice-amt-without-gst'][idx])

            item_entry['invoice_amt_sgst'] = float(invoice_post_data['invoice-amt-sgst'][idx])
            item_entry['invoice_amt_cgst'] = float(invoice_post_data['invoice-amt-cgst'][idx])
            item_entry['invoice_amt_igst'] = float(invoice_post_data['invoice-amt-igst'][idx])
            item_entry['invoice_amt_with_gst'] = float(invoice_post_data['invoice-amt-with-gst'][idx])

            processed_invoice_data['items'].append(item_entry)

    print(processed_invoice_data)
    return processed_invoice_data


def update_products_from_invoice(invoice_data_processed, request):
    for item in invoice_data_processed['items']:
        new_product = False
        if Product.objects.filter(user=request.user,
                                  model_no=item['invoice_model_no'],
                                  product_name=item['invoice_product'],
                                  product_hsn=item['invoice_hsn'],
                                  product_gst_percentage=item['invoice_gst_percentage']).exists():
            product = Product.objects.get(user=request.user,
                                          model_no=item['invoice_model_no'],
                                          product_name=item['invoice_product'],
                                          product_hsn=item['invoice_hsn'],
                                          product_gst_percentage=item['invoice_gst_percentage'])
        else:
            new_product = True
            product = Product(user=request.user,
                              model_no=item['invoice_model_no'],
                              product_name=item['invoice_product'],
                              product_hsn=item['invoice_hsn'],
                              product_gst_percentage=item['invoice_gst_percentage'])
        product.product_rate_with_gst = item['invoice_rate_with_gst']
        product.save()

        if new_product:
            create_inventory(product)


#  ================== Inventory methods ====================
def create_inventory(product):
    if not Inventory.objects.filter(user=product.user, product=product).exists():
        new_inventory = Inventory(user=product.user, product=product)
        new_inventory.save()

def update_inventory(invoice, request):
    if invoice.is_gst:
        description = "Sale - Auto Deduct"
    else:
        description = "Non-GST Sale - Auto Deduct"
    invoice_data =  json.loads(invoice.invoice_json)
    for item in invoice_data['items']:
        product = Product.objects.get(user=request.user,
                                      model_no=item['invoice_model_no'],
                                      product_name=item['invoice_product'],
                                      product_hsn=item['invoice_hsn'],
                                      product_gst_percentage=item['invoice_gst_percentage'])
        inventory = Inventory.objects.get(user=product.user, product=product)
        change = int(item['invoice_qty'])*(-1)
        inventory_log = InventoryLog(user=product.user,
                                     product=product,
                                     date=datetime.datetime.now(),
                                     change=change,
                                     change_type=4,
                                     associated_invoice=invoice,
                                     description=description)
        inventory_log.save()
        inventory.current_stock += change
        inventory.last_log = inventory_log
        inventory.save()


def remove_inventory_entries_for_invoice(invoice, user):
        inventory_logs = InventoryLog.objects.filter(user=user,
                                     associated_invoice=invoice)
        for inventory_log in inventory_logs:
            inventory_product = inventory_log.product
            inventory_log.delete()
            # update the inventory total
            inventory_obj = Inventory.objects.get(user=user, product=inventory_product)
            recalculate_inventory_total(inventory_obj, user)


def recalculate_inventory_total(inventory_obj, user):
    new_total = InventoryLog.objects.filter(user=user, product=inventory_obj.product).aggregate(Sum('change'))['change__sum']
    if not new_total:
        new_total = 0
    inventory_obj.current_stock = new_total
    inventory_obj.save()


def add_stock_to_inventory(product, quantity, description, user):
    inventory = Inventory.objects.get(user=user, product=product)
    inventory_log = InventoryLog(user=user,
                                 product=product,
                                 date=datetime.datetime.now(),
                                 change=quantity,
                                 change_type=1,
                                 description=description)
    inventory_log.save()
    recalculate_inventory_total(inventory, user)


# ================ Book Methods ===========================
def add_customer_book(customer):
    # check if customer already exists
    if Book.objects.filter(user=customer.user, customer=customer).exists():
        return
    book = Book(user=customer.user, customer=customer)
    book.save()


def auto_deduct_book_from_invoice(invoice):
    invoice_data =  json.loads(invoice.invoice_json)
    if invoice.is_gst:
        description = "Purchase - Auto Deduct"
    else:
        description = "Non-GST Sale - Auto Deduct"

    book = Book.objects.get(user=invoice.user, customer=invoice.invoice_customer)

    book_log = BookLog(parent_book=book,
                       date=invoice.invoice_date,
                       change_type=1,
                       change=(-1.0)*float(invoice_data['invoice_total_amt_with_gst']),
                       associated_invoice=invoice,
                       description=description)

    book_log.save()

    book.current_balance = book.current_balance + book_log.change
    book.last_log = book_log
    book.save()

def recalculate_book_current_balance(book_obj):
    new_total = BookLog.objects.filter(parent_book=book_obj, is_active=True, change_type__in=[0,1,2,3]).aggregate(Sum('change'))['change__sum']
    if not new_total:
        new_total = 0
    book_obj.current_balance = new_total
    book_obj.save()

# ================ Customer Methods ===========================
def add_customer_userid(customer):
    # check if customer not already exists
    if not Customer.objects.filter(user=customer.user, id=customer.id).exists():
        return
    customer = get_object_or_404(Customer, user=customer.user, id=customer.id)
    c_userid = f"{settings.PRODUCT_PREFIX}{customer.user.id}C{customer.id}"
    customer.customer_userid = c_userid.lower()
    customer.save()


# ================ Utility Methods ===========================
def parse_code_GS(input_code):
    if not input_code:
        return None
    # Regex to match the pattern
    pattern = r'([A-Za-z]+)(\d+)'
    # Find all matches
    matches = re.findall(pattern, input_code)
    # If no valid pattern found, return None
    if not matches:
        return None
    # Create a dictionary from the matches
    result = {key.upper(): int(value) for key, value in matches}
    return result

# ================ Quotation Cart =====================

def cart_product_payload(business_user):
    """
    Products for the cart, scoped to one business and field-whitelisted.

    productsjson() dumps Product.objects.values() — every column, including
    product_purchase_rate. That is the cost price, so it must never reach a cart
    that unauthenticated customers can open.
    """
    fields = (
        'id', 'model_no', 'product_name', 'product_hsn',
        'product_rate_with_gst', 'product_gst_percentage', 'product_discount',
        'product_image_url', 'product_category_id', 'product_division_category',
        'product_model_category', 'product_colour',
    )
    return list(Product.objects.filter(user=business_user).values(*fields))


class CartError(ValueError):
    """A cart/order could not be turned into a quotation. `str(err)` is user-safe."""


def create_cart_draft_quotation(business_user, items, *, existing_customer=None,
                                customer_fields=None, is_gst=True,
                                allow_discount=True, created_by_customer=False,
                                actor_label='staff', order_employee=None):
    """
    Server-authoritative core shared by the staff Quotation Cart and the mobile order
    flow. The client only ever sends product ids, quantities and (for staff/employee)
    per-line discounts — rate and GST% are ALWAYS re-read from the Product table here,
    so a tampered payload cannot reprice a line. Saves a DRAFT quotation and returns
    the created object plus the recomputed totals.

    Customer is either `existing_customer` (a saved Customer, trusted over any echoed
    fields) or, when None, built from `customer_fields` {name, phone, address, gst}.
    Raises CartError(user-safe message) on any validation failure.
    """
    from django.db import transaction
    from django.db.models import Max
    from .models import Quotation

    if not items:
        raise CartError('Cart is empty')

    # A GST quotation needs the customer's GSTIN, so a customer without one is silently
    # downgraded to non-GST — same rule as quotation_create() / invoice_create().
    if existing_customer is not None:
        customer_name = existing_customer.customer_name
        customer_phone = existing_customer.customer_phone or ''
        customer_address = existing_customer.customer_address or ''
        customer_gst = (existing_customer.customer_gst or '').strip().upper()
    else:
        fields = customer_fields or {}
        customer_name = (fields.get('name') or '').strip()
        if not customer_name:
            raise CartError('Customer name is required')
        customer_phone = (fields.get('phone') or '').strip()
        customer_address = (fields.get('address') or '').strip()
        customer_gst = (fields.get('gst') or '').strip().upper()
        if customer_gst and len(customer_gst) != 15:
            raise CartError('Customer GST must be 15 characters')

    is_gst = bool(is_gst)
    auto_downgraded_to_non_gst = is_gst and not customer_gst
    if auto_downgraded_to_non_gst:
        is_gst = False

    quotation_data = {
        'customer_name': customer_name,
        'customer_address': customer_address,
        'customer_phone': customer_phone,
        'customer_gst': customer_gst,
        'vehicle_number': '',
        'igstcheck': False,
        'items': [],
    }

    total_gross = total_discount = 0.0
    total_without_gst = total_sgst = total_cgst = total_igst = total_with_gst = 0.0

    for line in items:
        try:
            product = Product.objects.get(id=line.get('id'), user=business_user)
        except (Product.DoesNotExist, ValueError, TypeError):
            raise CartError('A product in your cart no longer exists. Please refresh.')

        try:
            qty = int(float(line.get('qty', 0)))
        except (ValueError, TypeError):
            qty = 0
        if qty < 1:
            raise CartError(f'Invalid quantity for {product.model_no}')

        # Discount is only honoured for actors allowed to set one (staff/employee).
        # Otherwise the product's own discount is used, so a forged payload from a
        # customer cannot mark down the price.
        line_discount = line.get('discount') if allow_discount else None

        item_entry = build_quotation_item(
            product, qty,
            igstcheck=quotation_data['igstcheck'],
            discount=line_discount,
        )

        gross = item_entry['invoice_rate_with_gst'] * qty
        total_gross += gross
        total_discount += gross - item_entry['invoice_amt_without_gst']

        total_without_gst += item_entry['invoice_amt_without_gst']
        total_sgst += item_entry['invoice_amt_sgst']
        total_cgst += item_entry['invoice_amt_cgst']
        total_igst += item_entry['invoice_amt_igst']
        total_with_gst += item_entry['invoice_amt_with_gst']

        quotation_data['items'].append(item_entry)

    quotation_data['invoice_total_amt_without_gst'] = round(total_without_gst, 2)
    quotation_data['invoice_total_amt_sgst'] = round(total_sgst, 2)
    quotation_data['invoice_total_amt_cgst'] = round(total_cgst, 2)
    quotation_data['invoice_total_amt_igst'] = round(total_igst, 2)
    quotation_data['invoice_total_amt_with_gst'] = round(total_with_gst, 2)

    today = datetime.date.today()

    with transaction.atomic():
        # select_for_update holds the row lock until commit so two concurrent
        # checkouts cannot read the same Max() and claim the same number.
        max_number = Quotation.objects.select_for_update().filter(
            user=business_user, is_gst=is_gst
        ).aggregate(Max('quotation_number'))['quotation_number__max']

        customer = existing_customer
        if customer is None:
            customer, _ = Customer.objects.get_or_create(
                user=business_user,
                customer_name=customer_name.upper(),
                defaults={
                    'customer_address': customer_address,
                    'customer_phone': customer_phone,
                    'customer_gst': customer_gst,
                },
            )

        new_quotation = Quotation(
            user=business_user,
            quotation_number=(max_number or 0) + 1,
            quotation_date=today,
            valid_until=today + datetime.timedelta(days=30),
            quotation_customer=customer,
            quotation_json=json.dumps(quotation_data),
            is_gst=is_gst,
            # Always DRAFT: the cart never touches inventory or books until a human
            # at the business approves it.
            status='DRAFT',
            created_from_cart=True,
            created_by_customer=created_by_customer,
            order_employee=order_employee,
            notes=f'Created from Quotation Cart ({actor_label})',
        )
        new_quotation.save()

    return {
        'quotation': new_quotation,
        'quotation_data': quotation_data,
        'customer': customer,
        'is_gst': is_gst,
        'gst_downgraded': auto_downgraded_to_non_gst,
        'customer_name': customer_name,
        'customer_phone': customer_phone,
        'totals': {
            'gross': round(total_gross, 2),
            'discount': round(total_discount, 2),
            'taxable': quotation_data['invoice_total_amt_without_gst'],
            'cgst': quotation_data['invoice_total_amt_cgst'],
            'sgst': quotation_data['invoice_total_amt_sgst'],
            'igst': quotation_data['invoice_total_amt_igst'],
            'grand_total': quotation_data['invoice_total_amt_with_gst'],
        },
    }


def _escape_md(text):
    """Escape special characters for Telegram MarkdownV2 format."""
    if not text:
        return ''
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    escaped = str(text)
    for ch in special_chars:
        escaped = escaped.replace(ch, f'\\{ch}')
    return escaped

# ================= Location Methods ===========================
import math

# ================= Purchases Log Utilities ====================================
def get_change_type_change(change_type, change):
    if change_type == '3':  # Others
        change = change
    elif change_type == '1':  # Purchased
        if float(change) > 0:
            change = -float(change)
    else:
        change = abs(float(change))
    return change

def get_vendor_instance(vendor, request):
    if vendor == '':
        vendor_instance = None
    else:
        vendor_instance = VendorPurchase.objects.get(user=request.user, id=vendor)
    return vendor_instance