# Django imports
from django.urls import path, include

# Local imports
from .views import (
    auth, profile, invoices, customers,
    books, products, inventory, purchases,
    features, views
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
    
    # Features URLs
    path('feature/upload', features.excel_upload, name='feature_upload'),
]