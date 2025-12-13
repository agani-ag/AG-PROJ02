# Django imports
from django.urls import path, include

# Local imports
from .views import (
    auth, profile, invoices, customers,
    books, products, inventory, purchases,
    vendor_purchase, features, views,
    expense_tracker, bank_details, graphs,
    purchase_invoices, gst_returns, gst_reconciliation,
    returns, customer_transactions
)

urlpatterns = [
    # Landing Page
    path('', views.landing_page, name='landing_page'),

    # Authentication URLs
    path('login', auth.login_view, name='login_view'),
    path('signup', auth.signup_view, name='signup_view'),
    path('logout', auth.logout_view, name='logout_view'),
    path('accounts/', include('django.contrib.auth.urls')),

    # Profile URLs
    path('profile', profile.user_profile, name='user_profile'),
    path('profile/edit', profile.user_profile_edit, name='user_profile_edit'),

    # Invoice URLs
    path('invoices', invoices.invoices, name='invoices'),
    path('invoices/nongst', invoices.non_gst_invoices, name='non_gst_invoices'),
    path('invoices/new', invoices.invoice_create, name='invoice_create'),
    path('invoice/<int:invoice_id>', invoices.invoice_viewer, name='invoice_viewer'),
    path('invoices/delete', invoices.invoice_delete, name='invoice_delete'),

    # Customer URLs
    path('customers', customers.customers, name='customers'),
    path('customers/add', customers.customer_add, name='customer_add'),
    path('customers/edit/<int:customer_id>', customers.customer_edit, name='customer_edit'),
    path('customers/delete', customers.customer_delete, name='customer_delete'),
    path('customersjson', customers.customersjson, name='customersjson'),
    # API Endpoints
    path('customers/api/add', customers.customer_api_add, name='customer_api_add'),
    path('customers/api/default_password', customers.customer_default_password, name='customer_default_password'),
    path('customers/api/all_userid_set', customers.customerall_userid_set, name='customerall_userid_set'),

    # Book URLs
    path('books', books.books, name='books'),
    path('books/<int:book_id>', books.book_logs, name='book_logs'),
    path('books/<int:book_id>/addupdate', books.book_logs_add, name='book_logs_add'),
    path('book/del/<int:booklog_id>', books.book_logs_del, name='book_logs_del'),
    # API Endpoints
    path('books/api/add', books.book_logs_api_add, name='book_logs_api_add'),

    # Product URLs
    path('products', products.products, name='products'),
    path('products/add', products.product_add, name='product_add'),
    path('products/edit/<int:product_id>', products.product_edit, name='product_edit'),
    path('products/delete', products.product_delete, name='product_delete'),
    path('productsjson', products.productsjson, name='productsjson'),
    # API Endpoints
    path('products/api/add', products.product_api_add, name='product_api_add'),

    # Inventory URLs
    path('inventory', inventory.inventory, name='inventory'),
    path('inventory/<int:inventory_id>', inventory.inventory_logs, name='inventory_logs'),
    path('inventory/<int:inventory_id>/addupdate', inventory.inventory_logs_add, name='inventory_logs_add'),
    path('inventory/del/<int:inventorylog_id>', inventory.inventory_logs_del, name='inventory_logs_del'),
    # API Endpoints
    path('inventory/api/stock/add', inventory.inventory_api_stock_add, name='inventory_api_stock_add'),

    # Purchase URLs
    path('purchases', purchases.purchases, name='purchases'),
    path('purchases/add', purchases.purchases_add, name='purchases_add'),
    path('purchases/edit/<int:pid>', purchases.purchases_edit, name='purchases_edit'),
    path('purchases/delete/<int:pid>', purchases.purchases_delete, name='purchases_delete'),

    # Vendor Purchase URLs
    path('purchases/vendors', vendor_purchase.vendors_purchase, name='vendors_purchase'),
    path('purchases/vendor/add', vendor_purchase.vendor_purchase_add, name='vendor_purchase_add'),
    path('purchases/vendor/edit/<int:vendor_purchase_id>', vendor_purchase.vendor_purchase_edit, name='vendor_purchase_edit'),
    path('purchases/vendor/delete', vendor_purchase.vendor_purchase_delete, name='vendor_purchase_delete'),
    
    # Expense Tracker URLs
    path('expensetracker', expense_tracker.expense_tracker, name='expense_tracker'),
    path('expensetracker/add', expense_tracker.expense_tracker_add, name='expense_tracker_add'),
    path('expensetracker/delete/<int:expense_id>', expense_tracker.expense_tracker_delete, name='expense_tracker_delete'),

    # Bank Details URLs
    path('bank_details', bank_details.bank_details, name='bank_details'),
    path('bank_details/add', bank_details.bank_details_add, name='bank_details_add'),
    path('bank_details/edit/<int:pk>', bank_details.bank_details_edit, name='bank_details_edit'),
    path('bank_details/delete/<int:pk>', bank_details.bank_details_delete, name='bank_details_delete'),

    # Features URLs
    path('feature/upload', features.excel_upload, name='feature_upload'),
    path('api/passkey-auth', auth.passkey_auth, name='passkey_auth'),
    path('download/sqlite', features.download_sqlite, name='download_sqlite'),

    # Graphs and Analytics URLs
    path('graphs/dashboard', graphs.sales_dashboard, name='sales_dashboard'),

    # GST Filing & Returns URLs
    path('gst/dashboard', gst_returns.gst_dashboard, name='gst_dashboard'),
    path('gst/gstr1', gst_returns.gstr1_report, name='gstr1_report'),
    path('gst/gstr3b', gst_returns.gstr3b_report, name='gstr3b_report'),
    path('gst/gstr9', gst_returns.gstr9_report, name='gstr9_report'),
    path('gst/gstr1/export', gst_returns.export_gstr1_json, name='export_gstr1_json'),
    path('gst/gstr9/export', gst_returns.export_gstr9_json, name='gstr9_export_json'),

    # Purchase Invoice URLs
    path('purchase-invoices', purchase_invoices.purchase_invoice_list, name='purchase_invoice_list'),
    path('purchase-invoices/add', purchase_invoices.purchase_invoice_add, name='purchase_invoice_add'),
    path('purchase-invoices/<int:pk>/edit', purchase_invoices.purchase_invoice_edit, name='purchase_invoice_edit'),
    path('purchase-invoices/<int:pk>', purchase_invoices.purchase_invoice_view, name='purchase_invoice_view'),
    path('purchase-invoices/<int:pk>/delete', purchase_invoices.purchase_invoice_delete, name='purchase_invoice_delete'),
    path('purchase-invoices/api/add', purchase_invoices.purchase_invoice_api_add, name='purchase_invoice_api_add'),
    
    # ITC Ledger
    path('gst/itc-ledger', purchase_invoices.itc_ledger, name='itc_ledger'),
    
    # GST Reconciliation URLs
    path('gst/reconciliation', gst_reconciliation.gstr2_reconciliation, name='gstr2_reconciliation'),
    path('gst/reconciliation/upload', gst_reconciliation.gstr2_upload, name='gstr2_upload'),
    path('gst/reconciliation/<int:reconciliation_id>/resolve', gst_reconciliation.reconciliation_mark_resolved, name='reconciliation_mark_resolved'),
    path('gst/reconciliation/export', gst_reconciliation.reconciliation_export, name='reconciliation_export'),
    
    # Audit Log URLs
    path('audit/logs', gst_reconciliation.audit_log_viewer, name='audit_log_viewer'),
    path('audit/logs/<int:log_id>', gst_reconciliation.audit_log_detail, name='audit_log_detail'),
    
    # Compliance & Analytics URLs
    path('gst/compliance', gst_reconciliation.compliance_tracker, name='compliance_tracker'),
    path('gst/analytics', gst_reconciliation.gst_analytics, name='gst_analytics'),
    
    # Return Invoice URLs
    path('returns', returns.return_invoices_list, name='return_invoices_list'),
    path('returns/create/<int:invoice_id>', returns.return_invoice_create, name='return_invoice_create'),
    path('returns/<int:return_id>', returns.return_invoice_detail, name='return_invoice_detail'),
    path('returns/<int:return_id>/print', returns.return_invoice_printer, name='return_invoice_printer'),
    path('returns/<int:return_id>/process', returns.return_invoice_process, name='return_invoice_process'),
    
    # Customer Payment URLs
    path('customers/payments', customer_transactions.customer_payments_list, name='customer_payments_list'),
    path('customers/payments/add', customer_transactions.customer_payment_add, name='customer_payment_add'),
    path('customers/payments/add/<int:customer_id>', customer_transactions.customer_payment_add, name='customer_payment_add_for_customer'),
    
    # Customer Discount URLs
    path('customers/discounts', customer_transactions.customer_discounts_list, name='customer_discounts_list'),
    path('customers/discounts/add', customer_transactions.customer_discount_add, name='customer_discount_add'),
    path('customers/discounts/add/<int:customer_id>', customer_transactions.customer_discount_add, name='customer_discount_add_for_customer'),
]