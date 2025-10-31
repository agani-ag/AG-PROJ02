# Django imports
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required

# Models
from ..models import Customer

# ================= Features Pages ==============================
@login_required
def excel_upload(request):
    context = {}
    business_uid = request.user.userprofile.business_uid
    customers_data = list(Customer.objects.filter(user=request.user).order_by('id').values())
    for customer in customers_data:
        customer.pop('id')
        customer.pop('user_id')
        customer.pop('is_mobile_user')
        customer.pop('customer_password')
        customer['id'] = customer.pop('customer_userid')
        for key, value in customer.items():
            if value in [None, 'None', 'null']:
                customer[key] = ''

    # Define Template Fields
    customer_fields = [
        "customer_name","customer_address","customer_phone",
        "customer_gst","customer_email",
    ]
    
    book_fields = [
        "date","change","associated_invoice"
    ]

    product_fields = [
        "model_no","product_name","product_hsn","product_stock",
        "product_discount","product_gst_percentage","product_rate_with_gst",
    ]

    stock_fields = ["model_no","product_stock"]

    # Initialize Template Configuration
    template_config = {
        "books": {},
        "product": {},
        "customer": {},
        "stock": {},
    }

    # Configure headers
    template_config["books"]["headers"] = book_fields
    template_config["product"]["headers"] = product_fields
    template_config["customer"]["headers"] = customer_fields
    template_config["stock"]["headers"] = stock_fields
    
    # Configure APIs
    template_config["books"]["api"] = f"/books/api/add?business_uid={business_uid}&notes=Added via Excel"
    template_config["product"]["api"] = f"/products/api/add?business_uid={business_uid}&notes=New Product Added & Stock Uploaded via Excel"
    template_config["customer"]["api"] = f"/customers/api/add?business_uid={business_uid}&notes=Uploaded via Excel"
    template_config["stock"]["api"] = f"/inventory/api/stock/add?business_uid={business_uid}&notes=Stock Uploaded via Excel"

    # Configure Data
    template_config["books"]["data"] = customers_data

    # Template Configuration With Whole Data
    context['template_config'] = template_config
    # return JsonResponse(template_config)
    return render(request, 'features/upload.html', context)