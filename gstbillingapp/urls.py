# Django imports
from django.urls import path, include

# Local imports
from .views import (
    auth, profile, invoices, customers,
    books, products, inventory, purchases,
    vendor_purchase, features, views,
    expense_tracker, bank_details, graphs,
    quotation, notifications, reports,
    location, asset
)

urlpatterns = [
    # Landing Page
    path('', views.landing_page, name='landing_page'),

    # Authentication URLs
    path('login', auth.login_view, name='login_view'),
    path('signup', auth.signup_view, name='signup_view'),
    path('logout', auth.logout_view, name='logout_view'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('api/passkey-auth', auth.passkey_auth, name='passkey_auth'),

    # Profile URLs
    path('profile', profile.user_profile, name='user_profile'),
    path('profile/edit', profile.user_profile_edit, name='user_profile_edit'),

    # Invoice URLs
    path('invoices', invoices.invoices, name='invoices'),
    path('invoices/ajax', invoices.invoices_ajax, name='invoices_ajax'),
    path('invoices/new', invoices.invoice_create, name='invoice_create'),
    path('invoice/<int:invoice_id>/', invoices.invoice_viewer, name='invoice_viewer'),
    path('invoices/delete', invoices.invoice_delete, name='invoice_delete'),
    path('invoices/push-to-books/<int:invoice_id>', invoices.invoice_push_to_books, name='invoice_push_to_books'),
    path('api/customer-invoice-filter/', invoices.customerInvoiceFilter, name='customer_invoice_filter'),

    # Quotation URLs
    path('quotations/', quotation.quotations, name='quotations'),
    path('quotations/ajax/', quotation.quotations_ajax, name='quotations_ajax'),
    path('quotations/new/', quotation.quotation_create, name='quotation_create'),
    path('quotation/<int:quotation_id>/', quotation.quotation_viewer, name='quotation_viewer'),
    path('quotation/edit/<int:quotation_id>', quotation.quotation_edit, name='quotation_edit'),
    path('quotation/delete/<int:quotation_id>', quotation.quotation_delete, name='quotation_delete'),
    path('quotation/convert/<int:quotation_id>', quotation.quotation_convert_to_invoice, name='quotation_convert_to_invoice'),
    path('quotation/reconvert/<int:quotation_id>', quotation.quotation_reconvert_to_invoice, name='quotation_reconvert_to_invoice'),
    path('quotation/approve/<int:quotation_id>', quotation.quotation_approve, name='quotation_approve'),
    path('quotation/update-customer/<int:quotation_id>', quotation.quotation_update_customer, name='quotation_update_customer'),
    path('quotation/update-status/<int:quotation_id>', quotation.quotation_update_status, name='quotation_update_status'),
    path('quotation/cart', quotation.quotation_cart, name='quotation_cart'),

    # Customer URLs
    path('customers', customers.customers, name='customers'),
    path('customers/add', customers.customer_add, name='customer_add'),
    path('customers/edit/<int:customer_id>', customers.customer_edit, name='customer_edit'),
    path('customers/delete', customers.customer_delete, name='customer_delete'),
    path('customersjson', customers.customersjson, name='customersjson'),
    # API Endpoints
    path('customers/api/add', customers.customer_api_add, name='customer_api_add'),
    path('customers/api/all_userid_set', customers.customerall_userid_set, name='customerall_userid_set'),
    path('customers/api/is_mobile_user', customers.customer_is_mobile_user, name='customer_is_mobile_user'),
    path('customers/api/default_password', customers.customer_default_password, name='customer_default_password'),

    # Book URLs
    path('books', books.books, name='books'),
    path('books/<int:book_id>', books.book_logs, name='book_logs'),
    path('books/<int:book_id>/addupdate', books.book_logs_add, name='book_logs_add'),
    path('book/del/<int:booklog_id>', books.book_logs_del, name='book_logs_del'),
    # Full Book Logs View
    path('books/full', books.book_logs_full, name='book_logs_full'),
    path('books/full/ajax', books.book_logs_full_ajax, name='book_logs_full_ajax'),
    path('books/fulladdupdate', books.book_logs_full_add, name='book_logs_full_add'),
    # API Endpoints
    path('books/api/add', books.book_logs_api_add, name='book_logs_api_add'),
    path('books/api/active', books.book_logs_api_active, name='book_logs_api_active'),
    path('customer/book/filter/', books.customerBookFilter, name='customer_book_filter'),
    path('customer/book/pending-logs', books.book_logs_pending, name='book_logs_pending'),
    path('books/api/roundoff', books.book_logs_api_roundoff, name='book_logs_api_roundoff'),
    path('books/api/recalculate', books.book_logs_recalculate, name='book_logs_api_recalculate'),
    path('books/api/recalculate-all', books.book_logs_recalculate_all, name='book_logs_api_recalculate_all'),

    # Product URLs
    path('products', products.products, name='products'),
    path('products/aggrid', products.products_aggrid, name='products_aggrid'),
    path('products/add', products.product_add, name='product_add'),
    path('products/edit/<int:product_id>', products.product_edit, name='product_edit'),
    path('products/delete', products.product_delete, name='product_delete'),
    path('productsjson', products.productsjson, name='productsjson'),
    path('categoriesjson', products.categoriesjson, name='categoriesjson'),
    # Product Category URLs
    path('product-categories', products.product_category_list, name='product_category_list'),
    path('product-categories/save', products.product_category_save, name='product_category_save'),
    path('product-categories/delete/<int:pk>', products.product_category_delete, name='product_category_delete'),
    # API Endpoints
    path('products/api/add', products.product_api_add, name='product_api_add'),
    path('products/api/aggrid-update', products.product_aggrid_update, name='product_aggrid_update'),

    # Inventory URLs
    path('inventory', inventory.inventory, name='inventory'),
    path('inventory/<int:inventory_id>', inventory.inventory_logs, name='inventory_logs'),
    path('inventory/<int:inventory_id>/addupdate', inventory.inventory_logs_add, name='inventory_logs_add'),
    path('inventory/del/<int:inventorylog_id>', inventory.inventory_logs_del, name='inventory_logs_del'),
    path('inventory/logs', inventory.inventory_logs_full, name='inventory_logs_full'),
    # API Endpoints
    path('inventory/api/stock-alert-level/add', inventory.invertory_stock_alert_update, name='invertory_stock_alert_update'),
    path('inventory/api/stock/add', inventory.inventory_api_stock_add, name='inventory_api_stock_add'),
    path('inventory/logs/ajax/', inventory.inventory_logs_ajax, name='inventory_logs_ajax'),
    path('inventory/chart/trend/', inventory.inventory_trend_chart, name='inventory_trend_chart'),
    path('inventory/chart/product/', inventory.inventory_product_chart, name='inventory_product_chart'),

    # Purchase URLs
    path('purchases_logs', purchases.purchases_logs, name='purchases_logs'),
    path('purchases_logs/add', purchases.purchases_logs_add, name='purchases_logs_add'),
    path('purchases_logs/delete/<int:pid>', purchases.purchases_logs_delete, name='purchases_logs_delete'),
    # Overdue Purchases
    path('purchases_logs/overdue', purchases.purchases_logs_overdue, name='purchases_logs_overdue'),
    path('purchases_logs/overdue/api', purchases.purchases_logs_overdue_api, name='purchases_logs_overdue_api'),

    # Vendor Purchase URLs
    path('purchases/vendors', vendor_purchase.vendors_purchase, name='vendors_purchase'),
    path('purchases/vendor/add', vendor_purchase.vendor_purchase_add, name='vendor_purchase_add'),
    path('purchases/vendor/edit/<int:vendor_purchase_id>', vendor_purchase.vendor_purchase_edit, name='vendor_purchase_edit'),
    path('purchases/vendor/delete', vendor_purchase.vendor_purchase_delete, name='vendor_purchase_delete'),
    path('purchases/vendor/logs/<int:vendor_purchase_id>', vendor_purchase.purchases_vendor_logs, name='purchases_vendor_logs'),
    # API Endpoints
    path('purchases/vendor/filter/', vendor_purchase.vendorPurchaseFilter, name='vendor_purchase_filter'),
    path('purchases/vendor/logs/add/', vendor_purchase.purchases_logs_add_api, name='purchases_logs_add_api'),
    
    # Expense Tracker URLs
    path('expensetracker', expense_tracker.expense_tracker, name='expense_tracker'),
    path('expensetracker/add', expense_tracker.expense_tracker_add, name='expense_tracker_add'),
    path('expensetracker/delete/<int:expense_id>', expense_tracker.expense_tracker_delete, name='expense_tracker_delete'),

    # Asset URLs
    path('assets', asset.assets, name='assets'),
    path('asset/add', asset.asset_add, name='asset_add'),
    path('asset/edit/<int:asset_id>', asset.asset_edit, name='asset_edit'),
    path('asset/delete/<int:asset_id>', asset.asset_delete, name='asset_delete'),
    # Asset Log URLs
    path('asset/log/<int:asset_id>', asset.asset_log, name='asset_log'),
    path('asset/log/add/<int:asset_id>', asset.asset_log_add, name='asset_log_add'),
    path('asset/log/delete/<int:log_id>', asset.asset_log_delete, name='asset_log_delete'),

    # Bank Details URLs
    path('bank_details', bank_details.bank_details, name='bank_details'),
    path('bank_details/add', bank_details.bank_details_add, name='bank_details_add'),
    path('bank_details/edit/<int:pk>', bank_details.bank_details_edit, name='bank_details_edit'),
    path('bank_details/delete/<int:pk>', bank_details.bank_details_delete, name='bank_details_delete'),
    # Cheque Leaf URLs
    path('cheque_leafs', bank_details.cheque_leafs, name='cheque_leafs'),
    path('cheque_leaf/add', bank_details.cheque_leaf_add, name='cheque_leaf_add'),
    path('cheque_leaf/edit/<int:pk>', bank_details.cheque_leaf_edit, name='cheque_leaf_edit'),
    path('cheque_leaf/delete/<int:pk>', bank_details.cheque_leaf_delete, name='cheque_leaf_delete'),
    path('api/cheque_leaf_reminder', bank_details.cheque_leaf_reminder_api, name='cheque_leaf_reminder_api'),

    # Features URLs
    path('liveshare', features.liveshare_page, name='liveshare_page'),
    path('feature/upload', features.excel_upload, name='feature_upload'),
    path('download/sqlite', features.download_sqlite, name='download_sqlite'),

    # Reports URLs
    path('reports/sales', reports.sales_report_pdf, name='sales_report'),
    path('reports/bi-dashboard', reports.bi_dashboard, name='bi_dashboard'),
    path('reports/inventory-dashboard', reports.inventory_dashboard, name='inventory_dashboard'),
    path('reports/ar-aging', reports.ar_aging_report, name='ar_aging_report'),
    path('reports/credit-aging', reports.credit_aging_report, name='credit_aging_report'),
    path('reports/customer-analysis', reports.customer_analysis, name='customer_analysis'),
    path('reports/overdue', reports.overdue_report, name='overdue_report'),
    path('reports/transactions', reports.transaction_report, name='transaction_report'),
    path('reports/inventory-transactions', reports.inventory_transaction_report, name='inventory_transaction_report'),
    path('reports/inventory-margin', reports.inventory_margin_report, name='inventory_margin_report'),
    path('api/reports/overdue', reports.overdue_report_api, name='overdue_report_api'),

    # Graphs and Analytics URLs
    path('graphs/dashboard', graphs.sales_dashboard, name='sales_dashboard'),
    path('graphs/books', graphs.customer_books_graph, name='customer_books_graph'),
    path('graphs/customer', graphs.customer_graph, name='customer_graph'),
    path('graphs/purchase-log', graphs.purchase_log_graph, name='purchase_log_graph'),
    path('graphs/expense-tracker', graphs.expense_tracker_graph, name='expense_tracker_graph'),
    path('graphs/customer-location-map', graphs.customer_location_map, name='customer_location_map'),
    
    # Notification URLs
    path('notifications/', notifications.notifications_page, name='notifications_page'),
    path('notifications/api/', notifications.notifications_api, name='notifications_api'),
    path('notifications/api/count/', notifications.notification_count_api, name='notification_count_api'),
    path('notifications/<int:notification_id>/mark-read/', notifications.notification_mark_read, name='notification_mark_read'),
    path('notifications/mark-all-read/', notifications.notification_mark_all_read, name='notification_mark_all_read'),
    path('notifications/<int:notification_id>/delete/', notifications.notification_delete, name='notification_delete'),
    path('notifications/delete-all-read/', notifications.notification_delete_all_read, name='notification_delete_all_read'),

    # Location Tracking URLs
    path("dashboard/customer/", location.customer_dashboard),
    path("dashboard/employee/", location.employee_dashboard),
    path("dashboard/admin/", location.admin_dashboard),

    path("api/location/push/", location.push_location),
    path("api/location/poll/", location.poll_locations),
    path("api/location/history/", location.route_history),
    path("api/location/geofence/", location.geofence_events),
]