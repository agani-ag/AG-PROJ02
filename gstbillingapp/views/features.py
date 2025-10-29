# Django imports
from django.shortcuts import render


# ================= Features Pages ==============================
def excel_upload(request):
    context = {}
    context['user'] = request.user
    context['customer'] = [ 
        "customer_name",
        "customer_address",
        "customer_phone",
        "customer_gst",
        "customer_email",
    ]
    context['product'] = [ 
        "model_no",
        "product_name",
        "product_hsn",
        "product_discount",
        "product_gst_percentage",
        "product_rate_with_gst",
    ]
    return render(request, 'features/upload.html', context)