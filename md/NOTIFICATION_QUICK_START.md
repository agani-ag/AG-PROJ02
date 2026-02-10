# Quick Start - Notification System Integration Examples

## Example 1: Add to Invoice Creation (invoices.py)

```python
# At the top of gstbillingapp/views/invoices.py, add:
from ..utils import notify_invoice_created

# In your invoice_create view, after creating the invoice:
@login_required
def invoice_create(request):
    if request.method == "POST":
        # ... your existing invoice creation code ...
        
        # After invoice is saved successfully:
        new_invoice = Invoice.objects.create(...)
        
        # ADD THIS LINE to create notification:
        notify_invoice_created(request.user, new_invoice)
        
        return redirect('invoices')
```

## Example 2: Add to Quotation Creation (quotation.py)

```python
# At the top of gstbillingapp/views/quotation.py, add:
from ..utils import notify_quotation_created, notify_quotation_approved

# In quotation_create view:
@login_required
def quotation_create(request):
    if request.method == "POST":
        # ... existing code ...
        
        new_quotation = Quotation.objects.create(...)
        
        # ADD THIS LINE:
        notify_quotation_created(request.user, new_quotation)
        
        return redirect('quotations')

# In quotation_approve view:
@login_required
def quotation_approve(request, quotation_id):
    quotation = get_object_or_404(Quotation, id=quotation_id, user=request.user)
    quotation.status = 'APPROVED'
    quotation.save()
    
    # ADD THIS LINE:
    notify_quotation_approved(request.user, quotation)
    
    return redirect('quotations')
```

## Example 3: Add to Customer Creation (customers.py)

```python
# At the top of gstbillingapp/views/customers.py, add:
from ..utils import create_notification

# In customer_add view, after customer is created:
@login_required
def customer_add(request):
    if request.method == "POST":
        # ... existing code ...
        
        new_customer = customer_form.save(commit=False)
        new_customer.user = request.user
        new_customer.save()
        
        # ADD THIS CODE:
        create_notification(
            request.user,
            "New Customer Added",
            f"Customer '{new_customer.customer_name}' has been added successfully",
            "CUSTOMER",
            link_url=f"/customers/edit/{new_customer.id}",
            link_text="View Customer"
        )
        
        return redirect('customers')
```

## Example 4: Payment Received Notification

```python
# In books.py or wherever you handle payments:
from ..utils import notify_payment_received

@login_required
def book_logs_add(request):
    if request.method == "POST":
        # ... your payment processing code ...
        
        if payment_type == "CREDIT":  # Payment received
            amount = float(request.POST.get('amount'))
            customer = get_object_or_404(Customer, id=customer_id)
            
            # ADD THIS LINE:
            notify_payment_received(request.user, customer, amount)
        
        return redirect('books')
```

## Example 5: Low Stock Alert

```python
# In inventory.py:
from ..utils import notify_low_stock

@login_required
def inventory_logs_add(request):
    if request.method == "POST":
        # ... after updating inventory ...
        
        inventory_obj = get_object_or_404(Inventory, id=inventory_id)
        
        # Check if stock is low
        if inventory_obj.quantity <= inventory_obj.stock_alert_level:
            # ADD THIS CODE:
            notify_low_stock(
                request.user,
                inventory_obj.product,
                inventory_obj.quantity
            )
        
        return redirect('inventory')
```

## Example 6: Generic Success/Error Notifications

```python
from ..utils import create_notification

# Success notification
def some_view(request):
    try:
        # Your code here
        result = perform_action()
        
        create_notification(
            request.user,
            "Action Successful",
            "The operation completed successfully",
            "SUCCESS"
        )
    except Exception as e:
        # Error notification
        create_notification(
            request.user,
            "Action Failed",
            f"An error occurred: {str(e)}",
            "ERROR"
        )
```

## Testing Your Notifications

### Step 1: Add a test notification to landing page

Edit `gstbillingapp/views/views.py`:

```python
from ..utils import create_notification

def landing_page(request):
    context = {}
    
    # TEST: Create a sample notification when landing page loads
    if request.user.is_authenticated:
        create_notification(
            request.user,
            "Welcome Back!",
            "You have successfully logged in to GST Billing System",
            "SUCCESS",
            link_url="/",
            link_text="Go to Home"
        )
    
    return render(request, 'landing_page.html', context)
```

### Step 2: Test the system

1. Run server: `python manage.py runserver`
2. Login to your account
3. You should see a notification badge on the navbar
4. Click "Notifications" in the navbar
5. You should see your test notification
6. Click on the notification to test navigation
7. Mark as read, delete, etc.

### Step 3: Remove test code

After confirming it works, remove the test notification from landing_page.

## All Available Notification Types

```python
"INFO"       # Blue - General information
"SUCCESS"    # Green - Success messages
"WARNING"    # Yellow - Warnings
"ERROR"      # Red - Errors
"INVOICE"    # Blue - Invoice related
"QUOTATION"  # Gray - Quotation related
"CUSTOMER"   # Blue - Customer related
"PRODUCT"    # Orange - Product related
"PAYMENT"    # Green - Payment related
"SYSTEM"     # Dark - System messages
```

## Common Patterns

### Pattern 1: Notify on Create
```python
object = Model.objects.create(...)
notify_xxx_created(request.user, object)
```

### Pattern 2: Notify on Update
```python
object.status = 'NEW_STATUS'
object.save()
create_notification(request.user, "Status Updated", "...", "INFO")
```

### Pattern 3: Notify on Delete
```python
name = object.name
object.delete()
create_notification(request.user, "Item Deleted", f"{name} was deleted", "WARNING")
```

### Pattern 4: Conditional Notifications
```python
if amount > 10000:
    create_notification(request.user, "Large Transaction", "...", "WARNING")
```

## Remember

- ✅ Always pass `request.user` as the first parameter
- ✅ Keep titles short (under 200 characters)
- ✅ Provide meaningful messages
- ✅ Add links when users need to take action
- ✅ Choose appropriate notification types
- ❌ Don't create too many notifications for minor actions
- ❌ Don't forget to handle exceptions

That's it! Start adding notifications to your views wherever you want to notify users.
