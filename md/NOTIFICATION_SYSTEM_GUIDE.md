# Notification System Documentation

## Overview

A comprehensive, scalable notification system has been added to your GST Billing application. Users can receive notifications, view them in a dedicated page, and navigate to relevant pages by clicking on notifications.

## Features

✅ **Notification Model** - Flexible model with multiple notification types
✅ **Auto-Refresh** - Notifications page auto-refreshes every 30 seconds
✅ **Badge Counter** - Navbar shows unread notification count
✅ **Multiple Types** - INFO, SUCCESS, WARNING, ERROR, INVOICE, QUOTATION, CUSTOMER, PRODUCT, PAYMENT, SYSTEM
✅ **Navigation Links** - Click notifications to navigate to relevant pages
✅ **Filters** - Filter by type and read/unread status
✅ **Mark as Read** - Individual and bulk marking
✅ **Soft Delete** - Notifications can be deleted without permanent removal
✅ **API Endpoints** - RESTful API for programmatic access
✅ **Utility Functions** - Easy-to-use helper functions for creating notifications

## Database Migration

The migration has already been created and applied:
- Migration file: `gstbillingapp/migrations/0005_notification_and_more.py`
- Status: ✅ Applied successfully

## How to Use - Simple Examples

### 1. Basic Notification

```python
from gstbillingapp.utils import create_notification

# Simple info notification
create_notification(
    request.user,
    "Welcome",
    "Welcome to GST Billing System!",
    "INFO"
)
```

### 2. Success Notification with Link

```python
from gstbillingapp.utils import create_notification

# After creating an invoice
create_notification(
    request.user,
    "Invoice Created",
    f"Invoice #{invoice.invoice_number} has been created successfully",
    "SUCCESS",
    link_url=f"/invoice/{invoice.id}/",
    link_text="View Invoice"
)
```

### 3. Warning Notification

```python
from gstbillingapp.utils import notify_low_stock

# Low stock alert
notify_low_stock(request.user, product_obj, 5)
```

### 4. Using Pre-built Helper Functions

```python
from gstbillingapp.utils import (
    notify_invoice_created,
    notify_quotation_created,
    notify_quotation_approved,
    notify_payment_received,
    notify_low_stock,
    notify_custom
)

# In your views - after creating an invoice
notify_invoice_created(request.user, invoice_obj)

# After creating a quotation
notify_quotation_created(request.user, quotation_obj)

# After approving a quotation
notify_quotation_approved(request.user, quotation_obj)

# After receiving payment
notify_payment_received(request.user, customer_obj, 5000)

# Low stock alert
notify_low_stock(request.user, product_obj, 5)

# Custom notification
notify_custom(
    request.user,
    "Custom Alert",
    "This is a custom message",
    "WARNING",
    "/some-page/",
    "Go to Page"
)
```

## Complete Function Reference

### create_notification()

**Main function to create notifications manually**

```python
from gstbillingapp.utils import create_notification

create_notification(
    user=request.user,              # Required: User object
    title="Notification Title",     # Required: Title (max 200 chars)
    message="Full message here",    # Required: Message text
    notification_type="INFO",       # Optional: Type (default: INFO)
    link_url="/page/123/",         # Optional: URL to navigate
    link_text="View Details",      # Optional: Link button text
    related_object_type="Invoice", # Optional: Model name
    related_object_id=123          # Optional: Object ID
)
```

**Notification Types:**
- `INFO` - General information (blue)
- `SUCCESS` - Success messages (green)
- `WARNING` - Warnings (yellow/orange)
- `ERROR` - Error messages (red)
- `INVOICE` - Invoice related (blue)
- `QUOTATION` - Quotation related (gray)
- `CUSTOMER` - Customer related (blue)
- `PRODUCT` - Product related (orange)
- `PAYMENT` - Payment related (green)
- `SYSTEM` - System messages (dark)

### Pre-built Helper Functions

#### notify_invoice_created(user, invoice)
```python
# Automatically creates notification when invoice is created
notify_invoice_created(request.user, invoice_obj)
```

#### notify_quotation_created(user, quotation)
```python
# Automatically creates notification when quotation is created
notify_quotation_created(request.user, quotation_obj)
```

#### notify_quotation_approved(user, quotation)
```python
# Notification when quotation is approved
notify_quotation_approved(request.user, quotation_obj)
```

#### notify_payment_received(user, customer, amount)
```python
# Payment received notification
notify_payment_received(request.user, customer_obj, 5000)
```

#### notify_low_stock(user, product, quantity)
```python
# Low stock alert
notify_low_stock(request.user, product_obj, 5)
```

#### get_unread_notification_count(user)
```python
# Get count of unread notifications
count = get_unread_notification_count(request.user)
```

#### mark_all_notifications_read(user)
```python
# Mark all as read programmatically
mark_all_notifications_read(request.user)
```

## Integration Examples

### Example 1: In Invoice Creation View

```python
from gstbillingapp.utils import notify_invoice_created

@login_required
def invoice_create(request):
    if request.method == "POST":
        # ... your invoice creation logic ...
        invoice = Invoice.objects.create(...)
        
        # Add notification
        notify_invoice_created(request.user, invoice)
        
        return redirect('invoices')
```

### Example 2: In Quotation Approval

```python
from gstbillingapp.utils import notify_quotation_approved

@login_required
def quotation_approve(request, quotation_id):
    quotation = get_object_or_404(Quotation, id=quotation_id, user=request.user)
    quotation.status = 'APPROVED'
    quotation.save()
    
    # Notify user
    notify_quotation_approved(request.user, quotation)
    
    return redirect('quotations')
```

### Example 3: Custom Business Logic

```python
from gstbillingapp.utils import create_notification

@login_required
def process_order(request):
    # Your business logic
    if order_total > 100000:
        # Send warning for large orders
        create_notification(
            request.user,
            "Large Order Alert",
            f"Order #{order.id} has a high value of ₹{order_total:,.2f}",
            "WARNING",
            link_url=f"/orders/{order.id}/",
            link_text="Review Order"
        )
```

### Example 4: Inventory Management

```python
from gstbillingapp.utils import notify_low_stock

@login_required
def check_inventory(request):
    # Check all products
    for inventory in Inventory.objects.filter(user=request.user):
        if inventory.quantity <= inventory.stock_alert_level:
            notify_low_stock(
                request.user,
                inventory.product,
                inventory.quantity
            )
```

## API Endpoints

### Get Notifications (AJAX)
```javascript
GET /notifications/api/
Parameters:
  - limit: Number of notifications (default: 10)
  - offset: Starting position (default: 0)
  - unread_only: true/false

Response:
{
    "success": true,
    "notifications": [...],
    "unread_count": 5,
    "total_count": 25,
    "has_more": true
}
```

### Get Unread Count Only
```javascript
GET /notifications/api/count/

Response:
{
    "success": true,
    "unread_count": 5
}
```

### Mark as Read
```javascript
POST /notifications/<notification_id>/mark-read/

Response:
{
    "success": true,
    "message": "Notification marked as read",
    "unread_count": 4
}
```

### Mark All as Read
```javascript
POST /notifications/mark-all-read/

Response:
{
    "success": true,
    "message": "All notifications marked as read",
    "unread_count": 0
}
```

### Delete Notification
```javascript
POST /notifications/<notification_id>/delete/

Response:
{
    "success": true,
    "message": "Notification deleted",
    "unread_count": 4
}
```

### Delete All Read
```javascript
POST /notifications/delete-all-read/

Response:
{
    "success": true,
    "message": "10 notifications deleted",
    "deleted_count": 10
}
```

## Frontend Usage

### JavaScript - Manual Refresh
```javascript
// Refresh notifications count
fetch('/notifications/api/count/')
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            console.log('Unread:', data.unread_count);
        }
    });
```

### JavaScript - Get Latest Notifications
```javascript
// Get latest 5 unread notifications
fetch('/notifications/api/?limit=5&unread_only=true')
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            data.notifications.forEach(notif => {
                console.log(notif.title, notif.message);
            });
        }
    });
```

## User Interface

### Navbar Badge
- Shows unread notification count
- Auto-updates every 30 seconds
- Red badge appears only when there are unread notifications

### Notifications Page
- **URL:** `/notifications/`
- **Features:**
  - List all notifications with icons and colors
  - Filter by type (Invoice, Quotation, Customer, etc.)
  - Filter by status (All, Unread, Read)
  - Mark individual as read
  - Mark all as read
  - Delete individual notifications
  - Delete all read notifications
  - Auto-refresh count every 30 seconds
  - Pagination (20 per page)
  - Click notification to navigate to related page

## Best Practices

### 1. When to Use Notifications

✅ **Good Use Cases:**
- Order/Invoice created
- Payment received
- Quotation approved/rejected
- Low stock alerts
- System updates
- Important business events

❌ **Avoid:**
- Too many notifications for minor actions
- Duplicate notifications for the same event
- Notifications for user's own actions (optional)

### 2. Notification Timing

```python
# Create notification AFTER successful database operation
invoice = Invoice.objects.create(...)
invoice.save()
# Now create notification
notify_invoice_created(request.user, invoice)
```

### 3. Error Handling

```python
try:
    # Your business logic
    invoice = create_invoice(...)
    notify_invoice_created(request.user, invoice)
except Exception as e:
    # Notify error
    create_notification(
        request.user,
        "Invoice Creation Failed",
        f"Error: {str(e)}",
        "ERROR"
    )
```

### 4. Batch Operations

```python
# When processing multiple items, group notifications
processed = 0
for item in items:
    process_item(item)
    processed += 1

# Single notification for batch
create_notification(
    request.user,
    "Batch Processing Complete",
    f"Successfully processed {processed} items",
    "SUCCESS"
)
```

## Database Model

```python
class Notification(models.Model):
    user                  # ForeignKey to User
    notification_type     # Type: INFO, SUCCESS, WARNING, etc.
    title                 # Title (max 200 chars)
    message              # Full message text
    link_url             # Optional navigation URL
    link_text            # Optional link button text
    is_read              # Read status
    is_deleted           # Soft delete flag
    created_at           # Timestamp
    read_at              # When marked as read
    related_object_type  # Optional: "Invoice", "Customer", etc.
    related_object_id    # Optional: Object ID
```

## Testing

### Manual Testing
1. Go to any view (e.g., create invoice)
2. Add notification code
3. Perform the action
4. Check notifications page at `/notifications/`
5. Verify badge count updates
6. Click notification to test navigation

### Example Test Code
```python
# Add to any view temporarily for testing
from gstbillingapp.utils import create_notification

create_notification(
    request.user,
    "Test Notification",
    "This is a test message",
    "INFO",
    "/",
    "Go Home"
)
```

## Troubleshooting

### Notifications Not Showing
1. Check if user is logged in
2. Verify notification was created in database
3. Check `is_deleted=False` and user matches
4. Clear browser cache
5. Check browser console for JavaScript errors

### Badge Not Updating
1. Check if JavaScript is enabled
2. Verify API endpoint `/notifications/api/count/` works
3. Check browser console for errors
4. Try manual page refresh

### Migration Issues
If you need to recreate migrations:
```bash
python manage.py makemigrations gstbillingapp
python manage.py migrate
```

## Summary

The notification system is now fully integrated and ready to use. Simply import the utility functions and call them wherever you need to notify users. The system handles all the UI, API, and database operations automatically.

**Quick Start:**
```python
from gstbillingapp.utils import notify_custom

# Anywhere in your views
notify_custom(
    request.user,
    "My Notification",
    "Something happened!",
    "SUCCESS"
)
```

The notification will appear in:
- Navbar badge (unread count)
- Notifications page with full details
- Auto-refresh every 30 seconds
