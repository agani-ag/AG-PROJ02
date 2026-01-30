# Django imports
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

# Models
from ..models import (
    Product, UserProfile,
    ProductCategory
)
# Utility functions
from ..utils import (
    create_inventory, add_stock_to_inventory
)
# Forms
from ..forms import ProductForm

# Python imports
import json

# ================= Product Views ==============================
@login_required
def products(request):
    context = {}
    context['products'] = Product.objects.filter(user=request.user).order_by('-id')
    return render(request, 'products/products.html', context)


@login_required
def product_edit(request, product_id):
    product_obj = get_object_or_404(Product, user=request.user, id=product_id)
    if request.method == "POST":
        product_form = ProductForm(request.POST, instance=product_obj)
        if product_form.is_valid():
            new_product = product_form.save()
            return redirect('products')
    context = {}
    context['product_form'] = ProductForm(instance=product_obj)
    context['id'] = product_obj.id
    return render(request, 'products/product_edit.html', context)


@login_required
def product_add(request):
    if request.method == "POST":
        product_form = ProductForm(request.POST)
        if product_form.is_valid():
            new_product = product_form.save(commit=False)
            new_product.user = request.user
            new_product.save()
            create_inventory(new_product)
            return redirect('products')
    context = {}
    context['product_form'] = ProductForm()
    return render(request, 'products/product_edit.html', context)


@login_required
def product_delete(request):
    if request.method == "POST":
        product_id = request.POST["product_id"]
        product_obj = get_object_or_404(Product, user=request.user, id=product_id)
        product_obj.delete()
    return redirect('products')


# ================= Product API Views ===========================
@login_required
def productsjson(request):
    products = list(Product.objects.filter(user=request.user).values())
    return JsonResponse(products, safe=False)


@csrf_exempt
def product_api_add(request):
    if request.method == "POST":
        business_uid = request.GET.get('business_uid', None)
        if not business_uid:
            return JsonResponse({'status': 'error', 'message': 'Business UID is required.'})
        user_profile = get_object_or_404(UserProfile, business_uid=business_uid)
        if user_profile:
            user = user_profile.user
        data = request.body.decode('utf-8')
        data = json.loads(data)
        inserted_count = 0
        not_inserted_count = 0
        for item in data:
            if item.get('model_no') == "" or item.get('model_no') is None:
                not_inserted_count += 1
            elif Product.objects.filter(user=user, model_no=item.get('model_no').upper()).exists():
                not_inserted_count += 1
            else:
                product = Product(
                    user=user,
                    model_no=item.get('model_no'),
                    product_name=item.get('product_name') or '',
                    product_hsn=item.get('product_hsn') or '',
                    product_discount=item.get('product_discount') or 0,
                    product_gst_percentage=item.get('product_gst_percentage') or 18,
                    product_rate_with_gst=item.get('product_rate_with_gst') or 0
                )
                product.save()
                create_inventory(product)
                product_stock = item.get('product_stock') or 0
                if int(product_stock) > 0:
                    add_stock_to_inventory(product, int(product_stock), "Initial stock", user)
                inserted_count += 1
        return JsonResponse({'status': 'success', 'message': f'{inserted_count} Products added successfully.\n{not_inserted_count} Products not added.\nTotal {len(data)} items.'})
    return JsonResponse({'status': 'error', 'message': 'Use POST method to add products.'})

# ================= Product Category Views ===========================
@login_required
def product_category_list(request):
    categories = ProductCategory.objects.filter(user=request.user).values('id', 'category_name')
    # Convert QuerySet to list for json_script
    return render(request, 'products/product_category.html', {'categories': list(categories)})


@login_required
def product_category_save(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            if 'id' in data and data['id']:
                # Update existing
                category = ProductCategory.objects.get(id=data['id'], user=request.user)
                category.category_name = data.get('category_name', '')
                category.save()
            else:
                # Create new
                category = ProductCategory.objects.create(
                    category_name=data.get('category_name', ''),
                    user=request.user
                )
            return JsonResponse({'success': True, 'id': category.id})
        except ProductCategory.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Category not found'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request'})


@login_required
def product_category_delete(request, pk):
    if request.method == "DELETE":
        try:
            category = ProductCategory.objects.get(id=pk, user=request.user)
            category.delete()
            return JsonResponse({'success': True})
        except ProductCategory.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Category not found'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request'})