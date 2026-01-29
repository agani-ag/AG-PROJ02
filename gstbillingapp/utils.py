# Django imports
from django.db.models import Sum
from gstbilling import settings
from django.shortcuts import get_object_or_404

# Python imports
import re
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


def customer_already_exists(user, customer_phone, customer_email, customer_gst):
    if Customer.objects.filter(user=user, customer_phone=customer_phone).exists() or \
       Customer.objects.filter(user=user, customer_email=customer_email).exists() or \
       Customer.objects.filter(user=user, customer_gst=customer_gst).exists():
        return True
    return False

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


# ================ Notification System Methods =================
def create_notification(user, title, message, notification_type='INFO', 
                       link_url=None, link_text=None, 
                       related_object_type=None, related_object_id=None):
    """
    Create a notification for a user.
    
    Usage Examples:
        # Simple notification
        create_notification(request.user, "Welcome", "Welcome to GST Billing System", "SUCCESS")
        
        # Notification with link
        create_notification(
            request.user, 
            "New Invoice", 
            "Invoice #1234 has been created",
            "INVOICE",
            link_url="/invoice/1234/",
            link_text="View Invoice"
        )
        
        # Notification with related object
        create_notification(
            request.user,
            "Payment Received",
            "Payment of ₹5000 received from Customer ABC",
            "PAYMENT",
            link_url="/customers/123/",
            link_text="View Customer",
            related_object_type="Customer",
            related_object_id=123
        )
    
    Args:
        user: User object
        title: Notification title (max 200 chars)
        message: Notification message
        notification_type: Type of notification (INFO, SUCCESS, WARNING, ERROR, 
                          INVOICE, QUOTATION, CUSTOMER, PRODUCT, PAYMENT, SYSTEM)
        link_url: Optional URL to navigate when clicked
        link_text: Optional text for the link button
        related_object_type: Optional model name (e.g., "Invoice", "Customer")
        related_object_id: Optional ID of the related object
    
    Returns:
        Notification object
    """
    from .models import Notification
    
    notification = Notification.objects.create(
        user=user,
        notification_type=notification_type,
        title=title[:200],  # Ensure max length
        message=message,
        link_url=link_url,
        link_text=link_text,
        related_object_type=related_object_type,
        related_object_id=related_object_id
    )
    
    # Send real-time notification via WebSocket
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        
        channel_layer = get_channel_layer()
        if channel_layer:
            # Send notification to user's WebSocket
            async_to_sync(channel_layer.group_send)(
                f"notifications_user_{user.id}",
                {
                    'type': 'notification_message',
                    'notification': {
                        'id': notification.id,
                        'title': notification.title,
                        'message': notification.message,
                        'notification_type': notification.notification_type,
                        'link_url': notification.link_url or '',
                        'link_text': notification.link_text or 'View',
                        'created_at': notification.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                        'icon_class': notification.get_icon_class(),
                        'badge_class': notification.get_badge_class(),
                    }
                }
            )
            
            # Send updated count
            unread_count = Notification.objects.filter(
                user=user, is_read=False, is_deleted=False
            ).count()
            
            async_to_sync(channel_layer.group_send)(
                f"notifications_user_{user.id}",
                {
                    'type': 'count_update',
                    'count': unread_count
                }
            )
    except Exception as e:
        # If WebSocket fails, continue silently
        print(f"WebSocket notification failed: {e}")
    
    return notification


def notify_invoice_created(user, invoice):
    """
    Create notification when invoice is created
    
    Usage: notify_invoice_created(request.user, invoice_obj)
    """
    return create_notification(
        user=user,
        title=f"Invoice #{invoice.invoice_number} Created",
        message=f"New invoice #{invoice.invoice_number} created for {invoice.invoice_customer.customer_name if invoice.invoice_customer else 'N/A'}",
        notification_type="INVOICE",
        link_url=f"/invoice/{invoice.id}/",
        link_text="View Invoice",
        related_object_type="Invoice",
        related_object_id=invoice.id
    )


def notify_quotation_created(user, quotation):
    """
    Create notification when quotation is created
    
    Usage: notify_quotation_created(request.user, quotation_obj)
    """
    return create_notification(
        user=user,
        title=f"Quotation #{quotation.quotation_number} Created",
        message=f"New quotation #{quotation.quotation_number} created for {quotation.quotation_customer.customer_name if quotation.quotation_customer else 'N/A'}",
        notification_type="QUOTATION",
        link_url=f"/quotation/{quotation.id}/",
        link_text="View Quotation",
        related_object_type="Quotation",
        related_object_id=quotation.id
    )


def notify_quotation_approved(user, quotation):
    """
    Create notification when quotation is approved
    
    Usage: notify_quotation_approved(request.user, quotation_obj)
    """
    return create_notification(
        user=user,
        title=f"Quotation #{quotation.quotation_number} Approved",
        message=f"Quotation #{quotation.quotation_number} has been approved and is ready for conversion",
        notification_type="SUCCESS",
        link_url=f"/quotation/{quotation.id}/",
        link_text="View Quotation",
        related_object_type="Quotation",
        related_object_id=quotation.id
    )


def notify_payment_received(user, customer, amount):
    """
    Create notification when payment is received
    
    Usage: notify_payment_received(request.user, customer_obj, 5000)
    """
    return create_notification(
        user=user,
        title="Payment Received",
        message=f"Payment of ₹{amount:,.2f} received from {customer.customer_name}",
        notification_type="PAYMENT",
        link_url=f"/customers/edit/{customer.id}",
        link_text="View Customer",
        related_object_type="Customer",
        related_object_id=customer.id
    )


def notify_low_stock(user, product, quantity):
    """
    Create notification for low stock alert
    
    Usage: notify_low_stock(request.user, product_obj, 5)
    """
    return create_notification(
        user=user,
        title="Low Stock Alert",
        message=f"Product '{product.product_name}' ({product.model_no}) has low stock: {quantity} units remaining",
        notification_type="WARNING",
        link_url="/products",
        link_text="View Products",
        related_object_type="Product",
        related_object_id=product.id
    )


def notify_custom(user, title, message, notification_type='INFO', 
                 link_url=None, link_text=None):
    """
    Create a custom notification with flexible parameters
    
    Usage: 
        notify_custom(
            request.user, 
            "Custom Alert", 
            "This is a custom message",
            "WARNING",
            "/some-page/",
            "Go to Page"
        )
    """
    return create_notification(
        user=user,
        title=title,
        message=message,
        notification_type=notification_type,
        link_url=link_url,
        link_text=link_text
    )


def get_unread_notification_count(user):
    """
    Get count of unread notifications for a user
    
    Usage: count = get_unread_notification_count(request.user)
    """
    from .models import Notification
    return Notification.objects.filter(user=user, is_read=False, is_deleted=False).count()


def mark_all_notifications_read(user):
    """
    Mark all notifications as read for a user
    
    Usage: mark_all_notifications_read(request.user)
    """
    from .models import Notification
    from datetime import datetime
    
    Notification.objects.filter(
        user=user, 
        is_read=False, 
        is_deleted=False
    ).update(is_read=True, read_at=datetime.now())