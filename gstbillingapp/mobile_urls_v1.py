# Django imports
from django.urls import path

# Local imports
from .views.mobile_v1 import (
    customer,
    customer_orders,
    admin_orders
)

urlpatterns = [
    # Customer URLs
    path('customer/home', customer.customer_home, name='v1customerhome'),
    path('customer/books', customer.customer_books, name='v1customerbooks'),
    path('customer/profile', customer.customer_profile, name='v1customerprofile'),
    path('customer/invoices', customer.customer_invoices, name='v1customerinvoices'),
    path('customer/invoice_viewer/<int:invoice_id>', customer.customer_invoice_viewer, name='v1customerinvoiceviewer'),
    path('customer/notifications', customer.customer_notifications, name='v1customernotifications'),
    
    # Customer Ordering URLs
    path('customer/products', customer_orders.customer_products_catalog, name='v1customerproducts'),
    path('customer/order/create', customer_orders.customer_create_order, name='v1customerordercreate'),
    path('customer/orders', customer_orders.customer_orders_list, name='v1customerorders'),
    path('customer/order/<int:quotation_id>', customer_orders.customer_order_detail, name='v1customerorderdetail'),
    path('customer/order/<int:quotation_id>/edit', customer_orders.customer_edit_order, name='v1customerorderedit'),
    path('customer/order/<int:quotation_id>/update', customer_orders.customer_update_order, name='v1customerorderupdate'),
    path('customer/order/<int:quotation_id>/delete', customer_orders.customer_delete_order, name='v1customerorderdelete'),
    path('customer/order/<int:quotation_id>/received', customer_orders.customer_order_received, name='v1customerorderreceived'),
    
    # Employee URLs
    path('home', customer.home, name='v1home'),
    path('books', customer.books, name='v1books'),
    path('invoices', customer.invoices, name='v1invoices'),
    path('products', customer.products, name='v1products'),
    path('customers', customer.customers, name='v1customers'),
    path('purchaselogs', customer.purchase_logs, name='v1purchaselogs'),
    path('expensestracker', customer.expenses_tracker, name='v1expensestracker'),
    path('notifications', customer.notifications, name='v1notifications'),
    
    # Admin Order Management URLs
    path('admin/orders', admin_orders.admin_orders_list, name='v1adminorders'),
    path('admin/order/<int:quotation_id>', admin_orders.admin_order_detail, name='v1adminorderdetail'),
    path('admin/order/<int:quotation_id>/edit', admin_orders.admin_order_edit, name='v1adminorderedit'),
    path('admin/order/<int:quotation_id>/update', admin_orders.admin_order_update, name='v1adminorderupdate'),
    path('admin/order/<int:quotation_id>/update-status', admin_orders.admin_order_update_status, name='v1adminorderupdatestatus'),
    path('admin/order/<int:quotation_id>/convert', admin_orders.admin_order_convert_to_invoice, name='v1adminorderconvert'),

    # API URLs
    path('customers/api', customer.customersapi, name='v1customersapi'),
    path('customer/api/books/add', customer.customers_book_add_api, name='v1customersbookaddapi'),
    path('customer/api/reset-password', customer.customers_reset_password_api, name='v1customersresetpasswordapi'),
    path('product/api/add-stock', customer.product_inventory_stock_add, name='v1productinventorystockaddapi'),
    path('api/notifications/count', customer.notifications_count_api, name='v1notificationscountapi'),
    path('api/notifications/mark-read', customer.notification_mark_read_api, name='v1notificationsmarkreadapi'),
]