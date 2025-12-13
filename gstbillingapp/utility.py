# Django imports
from django.db.models import Sum
from gstbilling import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone

# Python imports
import json
import datetime


# Model imports
from .models import Product
from .models import Inventory
from .models import InventoryLog
from .models import Book
from .models import BookLog
from .models import Customer


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
    if invoice.non_gst_mode:
        description = "Non-GST Sale - Auto Deduct"
    else:
        description = "Sale - Auto Deduct"
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
                                     date=timezone.now(),
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
                                 date=timezone.now(),
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
    if invoice.non_gst_mode:
        description = "Non-GST Sale - Auto Deduct"
    else:
        description = "Purchase - Auto Deduct"

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
    new_total = BookLog.objects.filter(parent_book=book_obj).aggregate(Sum('change'))['change__sum']
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


def customer_already_exists(user, customer_phone, customer_email, customer_gst):
    if Customer.objects.filter(user=user, customer_phone=customer_phone).exists() or \
       Customer.objects.filter(user=user, customer_email=customer_email).exists() or \
       Customer.objects.filter(user=user, customer_gst=customer_gst).exists():
        return True
    return False


# ================ Return Invoice Methods ===========================
def update_inventory_for_return(return_invoice, request):
    """
    Reverse inventory deduction - Add stock back for returned items
    """
    from .models import ReturnInvoice
    
    return_data = json.loads(return_invoice.return_items_json)
    
    # Get the User instance from UserProfile
    user = return_invoice.user.user
    
    for item in return_data.get('items', []):
        # Get product key (support both old and new formats)
        model_no = item.get('invoice_model_no', item.get('invoice_product', ''))
        product_name = item.get('invoice_product', '')
        product_hsn = item.get('invoice_hsn', '')
        gst_percentage = item.get('invoice_gst_percentage', 0)
        
        if not model_no or not product_name:
            continue  # Skip if essential data is missing
        
        try:
            # Try to find product by model_no first
            product = Product.objects.get(user=user, model_no=model_no)
        except Product.DoesNotExist:
            # If not found, try by product name and other attributes
            try:
                product = Product.objects.get(
                    user=user,
                    product_name=product_name,
                    product_hsn=product_hsn,
                    product_gst_percentage=gst_percentage
                )
            except Product.DoesNotExist:
                # Product doesn't exist, skip this item
                continue
        
        try:
            inventory = Inventory.objects.get(user=user, product=product)
        except Inventory.DoesNotExist:
            # Create inventory if it doesn't exist
            inventory = Inventory.objects.create(user=user, product=product, current_stock=0)
        
        # POSITIVE change for returns (add stock back)
        change = int(item.get('return_qty', 0))  # POSITIVE: +5 for 5 items returned
        
        if change <= 0:
            continue  # Skip if no quantity to return
        
        # Create InventoryLog with change_type=3 (Return)
        inventory_log = InventoryLog(
            user=user,
            product=product,
            date=timezone.now(),
            change=change,  # POSITIVE
            change_type=3,  # 3 = Return
            associated_invoice=return_invoice.parent_invoice,  # Link to original
            description=f"Return from Invoice #{return_invoice.parent_invoice.invoice_number}"
        )
        inventory_log.save()
        
        # Update inventory stock (increases)
        inventory.current_stock += change
        inventory.last_log = inventory_log
        inventory.save()


def credit_customer_book_from_return(return_invoice):
    """
    Credit customer balance for returned items
    """
    return_data = json.loads(return_invoice.return_items_json)
    
    # Get the User instance from UserProfile
    user = return_invoice.user.user
    
    book = Book.objects.get(user=user, 
                           customer=return_invoice.customer)
    
    # POSITIVE change for return (credit customer)
    book_log = BookLog(
        parent_book=book,
        date=return_invoice.return_date,
        change_type=3,  # 3 = Returned Items (already exists!)
        change=float(return_data['return_total_amt_with_gst']),  # POSITIVE
        associated_invoice=return_invoice.parent_invoice,  # Link to original
        description=f"Return - Invoice #{return_invoice.parent_invoice.invoice_number}"
    )
    book_log.save()
    
    # Update customer balance (reduces debt)
    book.current_balance = book.current_balance + book_log.change  # Adds positive = reduces debt
    book.last_log = book_log
    book.save()


def calculate_available_return_items(parent_invoice):
    """
    Calculate how many items from parent invoice can still be returned
    Returns dict with available quantities per item
    """
    from .models import ReturnInvoice
    
    invoice_data = json.loads(parent_invoice.invoice_json)
    available_items = {}
    
    # Get all previous returns for this invoice
    previous_returns = ReturnInvoice.objects.filter(parent_invoice=parent_invoice)
    
    # Calculate total returned quantity per item
    returned_quantities = {}
    for return_inv in previous_returns:
        return_data = json.loads(return_inv.return_items_json)
        for item in return_data.get('items', []):
            key = item.get('invoice_product', item.get('invoice_model_no', ''))
            if key:
                returned_quantities[key] = returned_quantities.get(key, 0) + item.get('return_qty', 0)
    
    # Calculate available quantities
    for item in invoice_data.get('items', []):
        key = item.get('invoice_product', item.get('invoice_model_no', ''))
        if not key:
            continue
            
        original_qty = item.get('invoice_qty', 0)
        returned_qty = returned_quantities.get(key, 0)
        available_qty = original_qty - returned_qty
        
        available_items[key] = {
            'original_qty': original_qty,
            'returned_qty': returned_qty,
            'available_qty': available_qty,
            'item_data': item
        }
    
    return available_items


def validate_return_data(return_data, parent_invoice):
    """
    Validate return invoice data
    Returns error message if invalid, None if valid
    """
    # Check return date
    try:
        return_date = datetime.datetime.strptime(return_data['return-date'], '%Y-%m-%d').date()
        invoice_date = parent_invoice.invoice_date
        if return_date < invoice_date:
            return "Error: Return date cannot be before invoice date"
    except:
        return "Error: Invalid return date format"
    
    # Get available items
    available_items = calculate_available_return_items(parent_invoice)
    
    # Validate each return item
    for idx, model_no in enumerate(return_data.getlist('return-model-no')):
        if model_no:
            try:
                return_qty = int(return_data.getlist('return-qty')[idx])
                if model_no not in available_items:
                    return f"Error: Item {model_no} not found in original invoice"
                
                if return_qty <= 0:
                    return f"Error: Return quantity must be positive for {model_no}"
                
                if return_qty > available_items[model_no]['available_qty']:
                    return f"Error: Cannot return {return_qty} of {model_no}. Only {available_items[model_no]['available_qty']} available"
            except:
                return f"Error: Invalid return quantity for {model_no}"
    
    return None


def get_next_return_invoice_number(user):
    """Get the next available return invoice number for user"""
    from .models import ReturnInvoice
    
    last_return = ReturnInvoice.objects.filter(user=user).order_by('-return_invoice_number').first()
    if last_return:
        return last_return.return_invoice_number + 1
    return 1