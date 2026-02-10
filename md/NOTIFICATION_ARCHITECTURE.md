# Notification System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     GST BILLING APPLICATION                      │
│                    NOTIFICATION SYSTEM FLOW                      │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  USER INTERFACE LAYER                                            │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────┐                    ┌──────────────────┐         │
│  │  NAVBAR    │                    │  NOTIFICATIONS   │         │
│  │            │                    │  PAGE            │         │
│  │ [Bell Icon]│ ◄────────────────► │                  │         │
│  │  Badge: 5  │   Click to open    │  • Filter        │         │
│  └────────────┘                    │  • Mark Read     │         │
│       │                            │  • Delete        │         │
│       │ Auto-refresh               │  • Navigate      │         │
│       │ every 30s                  │  • Paginate      │         │
│       ▼                            └──────────────────┘         │
│  [API Call]                               │                     │
│                                           │                     │
└───────────────────────────────────────────┼─────────────────────┘
                                            │
                                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  API ENDPOINTS (notifications.py)                                │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  GET  /notifications/                    → notifications_page   │
│  GET  /notifications/api/                → notifications_api    │
│  GET  /notifications/api/count/          → notification_count   │
│  POST /notifications/<id>/mark-read/     → mark_read           │
│  POST /notifications/mark-all-read/      → mark_all_read       │
│  POST /notifications/<id>/delete/        → delete_notification │
│  POST /notifications/delete-all-read/    → delete_all_read     │
│                                                                  │
└───────────────────────────────────────────┬──────────────────────┘
                                            │
                                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  DATABASE LAYER (models.py)                                      │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Notification Model                                       │   │
│  ├──────────────────────────────────────────────────────────┤   │
│  │  • id                                                     │   │
│  │  • user (FK)                                              │   │
│  │  • notification_type (INFO/SUCCESS/WARNING/ERROR/etc)    │   │
│  │  • title (max 200 chars)                                 │   │
│  │  • message (text)                                         │   │
│  │  • link_url (optional)                                    │   │
│  │  • link_text (optional)                                   │   │
│  │  • is_read (boolean)                                      │   │
│  │  • is_deleted (boolean - soft delete)                     │   │
│  │  • created_at (timestamp)                                 │   │
│  │  • read_at (timestamp)                                    │   │
│  │  • related_object_type (optional)                         │   │
│  │  • related_object_id (optional)                           │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└───────────────────────────────────────────┬──────────────────────┘
                                            │
                                            ▲
                                            │
┌──────────────────────────────────────────┴────────────────────────┐
│  UTILITY FUNCTIONS (utils.py)                                    │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  create_notification(user, title, message, type...)    │     │
│  └────────────────────────────────────────────────────────┘     │
│                          │                                       │
│                          ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Pre-built Helper Functions:                             │   │
│  │                                                          │   │
│  │  • notify_invoice_created(user, invoice)                │   │
│  │  • notify_quotation_created(user, quotation)            │   │
│  │  • notify_quotation_approved(user, quotation)           │   │
│  │  • notify_payment_received(user, customer, amount)      │   │
│  │  • notify_low_stock(user, product, quantity)            │   │
│  │  • notify_custom(user, title, message, type, ...)       │   │
│  │  • get_unread_notification_count(user)                  │   │
│  │  • mark_all_notifications_read(user)                    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                          ▲                                       │
└──────────────────────────┼───────────────────────────────────────┘
                           │
                           │ Called from
                           │
┌──────────────────────────┴───────────────────────────────────────┐
│  YOUR EXISTING VIEWS (Integration Points)                        │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  invoices.py     ──►  notify_invoice_created()                   │
│  quotation.py    ──►  notify_quotation_created()                 │
│  quotation.py    ──►  notify_quotation_approved()                │
│  books.py        ──►  notify_payment_received()                  │
│  inventory.py    ──►  notify_low_stock()                         │
│  customers.py    ──►  create_notification()                      │
│  products.py     ──►  create_notification()                      │
│  ...any view...  ──►  notify_custom()                            │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## Data Flow Examples

### Creating a Notification

```
User Action (e.g., Create Invoice)
        │
        ▼
View Function (invoices.py)
        │
        ├──► Save Invoice to Database
        │
        └──► notify_invoice_created(user, invoice)
                    │
                    ▼
            create_notification()
                    │
                    ▼
            Notification.objects.create(...)
                    │
                    ▼
            Database (Notification table)
```

### Viewing Notifications

```
User clicks Notifications in Navbar
        │
        ▼
GET /notifications/
        │
        ▼
notifications_page(request)
        │
        ├──► Query: Notification.objects.filter(user=request.user)
        │
        ├──► Apply filters (type, status)
        │
        ├──► Paginate (20 per page)
        │
        └──► Render template with data
                    │
                    ▼
            notifications.html displays list
                    │
                    ├──► Shows icons & colors
                    ├──► Shows mark as read buttons
                    ├──► Shows navigation links
                    └──► Auto-refresh count every 30s
```

### Auto-Refresh Badge

```
Page Load (any page with navbar)
        │
        ▼
JavaScript: updateNotificationBadge()
        │
        ▼
GET /notifications/api/count/
        │
        ▼
notification_count_api(request)
        │
        ├──► Count unread notifications
        │
        └──► Return JSON: {unread_count: 5}
                    │
                    ▼
            JavaScript updates badge number
                    │
                    └──► Repeat every 30 seconds
```

## File Structure

```
gstbillingapp/
│
├── models.py                           ✅ Notification model added
│   └── class Notification
│
├── views/
│   ├── notifications.py                ✅ NEW - All notification views
│   │   ├── notifications_page()
│   │   ├── notifications_api()
│   │   ├── notification_mark_read()
│   │   ├── notification_mark_all_read()
│   │   ├── notification_delete()
│   │   ├── notification_delete_all_read()
│   │   └── notification_count_api()
│   │
│   └── [your existing views]           ⚠️ Add notification calls here
│       ├── invoices.py
│       ├── quotation.py
│       ├── customers.py
│       └── ...
│
├── templates/
│   ├── navbar.html                     ✅ Modified - Added menu & badge
│   └── notifications/
│       └── notifications.html          ✅ NEW - Full notification UI
│
├── utils.py                            ✅ Modified - Added 9 functions
│   ├── create_notification()
│   ├── notify_invoice_created()
│   ├── notify_quotation_created()
│   ├── notify_quotation_approved()
│   ├── notify_payment_received()
│   ├── notify_low_stock()
│   ├── notify_custom()
│   ├── get_unread_notification_count()
│   └── mark_all_notifications_read()
│
├── urls.py                             ✅ Modified - Added 7 URL patterns
│   └── Notification routes
│
├── admin.py                            ✅ Modified - Registered Notification
│   └── NotificationAdmin
│
└── migrations/
    └── 0005_notification_and_more.py   ✅ NEW - Applied successfully
```

## Integration Checklist

To use notifications in your views, follow this pattern:

```python
# Step 1: Import at the top of your view file
from ..utils import notify_invoice_created  # or any other function

# Step 2: Call after successful operation
@login_required
def your_view(request):
    if request.method == "POST":
        # Your business logic
        obj = YourModel.objects.create(...)
        
        # Create notification (this is the only line you need!)
        notify_invoice_created(request.user, obj)
        
        return redirect('somewhere')
```

## Testing Checklist

- [x] Django check passes
- [x] Migration created
- [x] Migration applied
- [x] Models imported correctly
- [x] Views created
- [x] Templates created
- [x] URLs configured
- [x] Admin registered
- [ ] Manual testing (to be done by you):
  - [ ] Create a test notification
  - [ ] Check navbar badge appears
  - [ ] Visit /notifications/ page
  - [ ] Mark as read
  - [ ] Delete notification
  - [ ] Test filters
  - [ ] Test auto-refresh

## Summary

**What was implemented:**
- ✅ Complete notification system
- ✅ 10 notification types
- ✅ Auto-refresh every 30 seconds
- ✅ Navbar badge with counter
- ✅ Dedicated notifications page
- ✅ 9 utility functions
- ✅ 7 API endpoints
- ✅ Full CRUD operations
- ✅ Filters and pagination
- ✅ Navigation links
- ✅ Django admin integration
- ✅ Complete documentation

**Zero breaking changes to existing code!**
