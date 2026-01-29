# 🔔 Notification System - Quick Reference Card

## 📦 One-Line Usage (Most Common)

```python
from gstbillingapp.utils import notify_custom

notify_custom(request.user, "Title", "Message", "SUCCESS")
```

## 🎯 Pre-Built Functions (Copy & Paste)

### Invoice Created
```python
from gstbillingapp.utils import notify_invoice_created
notify_invoice_created(request.user, invoice_obj)
```

### Quotation Created
```python
from gstbillingapp.utils import notify_quotation_created
notify_quotation_created(request.user, quotation_obj)
```

### Quotation Approved
```python
from gstbillingapp.utils import notify_quotation_approved
notify_quotation_approved(request.user, quotation_obj)
```

### Payment Received
```python
from gstbillingapp.utils import notify_payment_received
notify_payment_received(request.user, customer_obj, amount)
```

### Low Stock Alert
```python
from gstbillingapp.utils import notify_low_stock
notify_low_stock(request.user, product_obj, quantity)
```

## 🎨 Notification Types

| Type | Color | Use For |
|------|-------|---------|
| `INFO` | Blue | General information |
| `SUCCESS` | Green | Success messages |
| `WARNING` | Yellow | Warnings |
| `ERROR` | Red | Errors |
| `INVOICE` | Blue | Invoice related |
| `QUOTATION` | Gray | Quotation related |
| `CUSTOMER` | Blue | Customer related |
| `PRODUCT` | Orange | Product related |
| `PAYMENT` | Green | Payment related |
| `SYSTEM` | Dark | System messages |

## 🔗 With Navigation Link

```python
from gstbillingapp.utils import create_notification

create_notification(
    request.user,
    "Order Ready",
    "Your order #1234 is ready for delivery",
    "SUCCESS",
    link_url="/orders/1234/",
    link_text="View Order"
)
```

## 📊 Get Unread Count

```python
from gstbillingapp.utils import get_unread_notification_count
count = get_unread_notification_count(request.user)
```

## ✅ Mark All Read

```python
from gstbillingapp.utils import mark_all_notifications_read
mark_all_notifications_read(request.user)
```

## 🌐 Access Points

| What | Where | URL |
|------|-------|-----|
| View All | Navbar → Notifications | `/notifications/` |
| Badge | Navbar (auto-updates) | - |
| Admin | Django Admin | `/admin/` → Notifications |

## 🔄 Auto-Refresh

✅ Navbar badge updates every 30 seconds automatically
✅ Notifications page updates count every 30 seconds
✅ No manual refresh needed!

## 🧪 Quick Test

Add this to any view:
```python
from gstbillingapp.utils import notify_custom
notify_custom(request.user, "Test", "It works!", "SUCCESS", "/", "Home")
```

Then:
1. Perform the action
2. Check navbar for badge
3. Click "Notifications"
4. See your test notification!

## 📁 Files Created

- `gstbillingapp/views/notifications.py`
- `gstbillingapp/templates/notifications/notifications.html`
- `gstbillingapp/migrations/0005_notification_and_more.py`

## 📝 Files Modified

- `gstbillingapp/models.py` (added Notification model)
- `gstbillingapp/utils.py` (added 9 functions)
- `gstbillingapp/urls.py` (added 7 routes)
- `gstbillingapp/templates/navbar.html` (added menu & badge)
- `gstbillingapp/admin.py` (registered Notification)

## 🎓 Full Documentation

Read these for complete details:
1. `NOTIFICATION_SYSTEM_GUIDE.md` - Full reference
2. `NOTIFICATION_QUICK_START.md` - Integration examples
3. `NOTIFICATION_ARCHITECTURE.md` - System design
4. `NOTIFICATION_IMPLEMENTATION_SUMMARY.md` - What was done

## ⚡ Common Patterns

### After Create
```python
obj = Model.objects.create(...)
notify_xxx_created(request.user, obj)
```

### After Update
```python
obj.status = 'NEW'
obj.save()
create_notification(request.user, "Updated", "Status changed", "INFO")
```

### Conditional
```python
if amount > 10000:
    create_notification(request.user, "Alert", "Large amount", "WARNING")
```

### Error Handling
```python
try:
    # do something
    create_notification(request.user, "Success", "Done", "SUCCESS")
except Exception as e:
    create_notification(request.user, "Error", str(e), "ERROR")
```

## 🚀 Status

✅ Models created
✅ Migrations applied
✅ Views created
✅ Templates created
✅ URLs configured
✅ Admin registered
✅ Zero errors
✅ Production ready!

## 🎉 That's It!

Start adding `notify_xxx()` calls to your views and users will start receiving notifications!
