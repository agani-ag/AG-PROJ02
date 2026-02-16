# Django imports
from django.contrib import messages
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
    context['products'] = Product.objects.filter(user=request.user).select_related(
        'product_category', 'product_category__parent_category'
    ).order_by('-id')
    return render(request, 'products/products.html', context)


@login_required
def product_edit(request, product_id):
    product_obj = get_object_or_404(Product, user=request.user, id=product_id)
    if request.method == "POST":
        product_form = ProductForm(request.POST, instance=product_obj, user=request.user)
        if product_form.is_valid():
            new_product = product_form.save()
            return redirect('products')
    context = {}
    context['product_category_list'] = ProductCategory.objects.filter(
        user=request.user, parent_category__isnull=False
    ).select_related('parent_category').values('id', 'category_name', 'parent_category__category_name')
    context['product_form'] = ProductForm(instance=product_obj, user=request.user)
    context['id'] = product_obj.id
    return render(request, 'products/product_edit.html', context)


@login_required
def product_add(request):
    if request.method == "POST":
        # Check for duplicate model_no for the same user
        if Product.objects.filter(user=request.user, model_no=request.POST.get('model_no').upper()).exists():
            context = {}
            messages.warning(request, "Model No already exists. Please use a different Model No.")
            context['product_form'] = ProductForm(request.POST, user=request.user)
            context['product_category_list'] = ProductCategory.objects.filter(
                user=request.user, parent_category__isnull=False
            ).select_related('parent_category').values('id', 'category_name', 'parent_category__category_name')
            return render(request, 'products/product_edit.html', context)
        # Save new product
        product_form = ProductForm(request.POST, user=request.user)
        if product_form.is_valid():
            new_product = product_form.save(commit=False)
            new_product.user = request.user
            new_product.save()
            create_inventory(new_product)
            return redirect('products')
    context = {}
    context['product_form'] = ProductForm(user=request.user)
    context['product_category_list'] = ProductCategory.objects.filter(
        user=request.user, parent_category__isnull=False
    ).select_related('parent_category').values('id', 'category_name', 'parent_category__category_name')
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
    from django.db.models import Count
    # Get all categories with parent info and product count
    categories = ProductCategory.objects.filter(user=request.user).select_related(
        'parent_category'
    ).annotate(
        product_count=Count('product')
    )
    
    # Separate parent and child categories
    parent_categories = []
    child_categories = []
    
    for cat in categories:
        cat_data = {
            'id': cat.id,
            'category_name': cat.category_name,
            'parent_category_id': cat.parent_category.id if cat.parent_category else None,
            'parent_category_name': cat.parent_category.category_name if cat.parent_category else None,
            'product_count': cat.product_count,
            'full_path': cat.get_full_path(),
            'is_parent': cat.is_parent()
        }
        if cat.is_parent():
            parent_categories.append(cat_data)
        else:
            child_categories.append(cat_data)
    
    return render(request, 'products/product_category.html', {
        'categories': parent_categories + child_categories,
        'parent_categories': parent_categories,
        'child_categories': child_categories
    })


@login_required
def product_category_save(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            
            # Handle batch save (array of categories)
            if isinstance(data, list):
                saved_count = 0
                for item in data:
                    parent_id = item.get('parent_category_id')
                    parent_category = None
                    if parent_id:
                        try:
                            parent_category = ProductCategory.objects.get(id=parent_id, user=request.user)
                        except ProductCategory.DoesNotExist:
                            pass
                    
                    if 'id' in item and item['id']:
                        # Update existing
                        category = ProductCategory.objects.get(id=item['id'], user=request.user)
                        category.category_name = item.get('category_name', '')
                        category.parent_category = parent_category
                        category.save()
                    else:
                        # Create new
                        category = ProductCategory.objects.create(
                            category_name=item.get('category_name', ''),
                            parent_category=parent_category,
                            user=request.user
                        )
                        item['id'] = category.id
                    saved_count += 1
                return JsonResponse({'success': True, 'saved_count': saved_count, 'data': data})
            
            # Handle single save
            else:
                parent_id = data.get('parent_category_id')
                parent_category = None
                if parent_id:
                    try:
                        parent_category = ProductCategory.objects.get(id=parent_id, user=request.user)
                    except ProductCategory.DoesNotExist:
                        pass
                
                if 'id' in data and data['id']:
                    # Update existing
                    category = ProductCategory.objects.get(id=data['id'], user=request.user)
                    category.category_name = data.get('category_name', '')
                    category.parent_category = parent_category
                    category.save()
                else:
                    # Create new
                    category = ProductCategory.objects.create(
                        category_name=data.get('category_name', ''),
                        parent_category=parent_category,
                        user=request.user
                    )
                return JsonResponse({'success': True, 'id': category.id, 'full_path': category.get_full_path()})
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


# ================= AG Grid Products Views ==============================
@login_required
def products_aggrid(request):
    """AG Grid products page with inline editing"""
    from ..models import Inventory
    context = {}
    
    # Get all products with categories
    products = Product.objects.filter(user=request.user).select_related(
        'product_category', 'product_category__parent_category'
    ).order_by('-id')
    
    # Get all categories for dropdown
    categories = ProductCategory.objects.filter(
        user=request.user, parent_category__isnull=False
    ).select_related('parent_category').order_by('parent_category__category_name', 'category_name')
    
    # Prepare product data for AG Grid
    products_data = []
    for product in products:
        # Get inventory data
        try:
            inventory = Inventory.objects.filter(product=product, user=request.user).first()
            if inventory:
                current_stock = inventory.current_stock
                alert_level = inventory.alert_level
            else:
                current_stock = 0
                alert_level = 0
        except Inventory.MultipleObjectsReturned:
            # If multiple inventories exist, take the first one
            inventory = Inventory.objects.filter(product=product, user=request.user).first()
            current_stock = inventory.current_stock if inventory else 0
            alert_level = inventory.alert_level if inventory else 0
        except Exception:
            current_stock = 0
            alert_level = 0
        
        products_data.append({
            'id': product.id,
            'model_no': product.model_no,
            'product_name': product.product_name or '',
            'product_hsn': product.product_hsn or '',
            'product_discount': product.product_discount,
            'product_gst_percentage': product.product_gst_percentage,
            'product_rate_with_gst': product.product_rate_with_gst,
            'product_category_id': product.product_category.id if product.product_category else None,
            'product_category_name': product.product_category.get_full_path() if product.product_category else '',
            'parent_category': product.product_category.parent_category.category_name if product.product_category and product.product_category.parent_category else '',
            'child_category': product.product_category.category_name if product.product_category else '',
            'current_stock': current_stock,
            'alert_level': alert_level
        })
    
    # Prepare categories for dropdown
    categories_data = []
    for category in categories:
        categories_data.append({
            'id': category.id,
            'name': category.get_full_path(),
            'parent': category.parent_category.category_name if category.parent_category else '',
            'child': category.category_name
        })
    
    context['products_json'] = json.dumps(products_data)
    context['categories_json'] = json.dumps(categories_data)
    context['products_count'] = len(products_data)
    
    return render(request, 'products/products_aggrid.html', context)


@csrf_exempt
@login_required
def product_aggrid_update(request):
    """API endpoint to update product from AG Grid"""
    from ..models import Inventory, InventoryLog
    from datetime import datetime
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            product_id = data.get('id')
            
            if not product_id:
                return JsonResponse({'success': False, 'error': 'Product ID is required'})
            
            # Get product
            product = Product.objects.get(id=product_id, user=request.user)
            
            # Update fields - only update if value is provided and not empty
            if 'model_no' in data and data['model_no']:
                # Check for duplicate model_no
                existing = Product.objects.filter(
                    user=request.user, model_no=data['model_no']
                ).exclude(id=product_id)
                if existing.exists():
                    return JsonResponse({'success': False, 'error': f"Model No '{data['model_no']}' already exists"})
                product.model_no = data['model_no']
            
            if 'product_name' in data:
                # Allow empty string for product_name (it's optional)
                product.product_name = data['product_name'] if data['product_name'] else ''
            
            if 'product_hsn' in data:
                # Allow empty string for HSN (it's optional)
                product.product_hsn = data['product_hsn'] if data['product_hsn'] else ''
            
            if 'product_discount' in data and data['product_discount'] is not None:
                product.product_discount = float(data['product_discount'])
            
            if 'product_gst_percentage' in data and data['product_gst_percentage'] is not None:
                product.product_gst_percentage = float(data['product_gst_percentage'])
            
            if 'product_rate_with_gst' in data and data['product_rate_with_gst'] is not None:
                product.product_rate_with_gst = float(data['product_rate_with_gst'])
            
            if 'product_category_id' in data:
                if data['product_category_id']:
                    category = ProductCategory.objects.get(
                        id=data['product_category_id'], user=request.user
                    )
                    product.product_category = category
                else:
                    product.product_category = None
            
            product.save()
            
            # Handle inventory updates
            inventory_updated = False
            if 'current_stock' in data or 'alert_level' in data:
                # Try to get existing inventory, handle multiple records
                inventory = Inventory.objects.filter(
                    product=product,
                    user=request.user
                ).first()
                
                if not inventory:
                    # Create new inventory if none exists
                    inventory = Inventory.objects.create(
                        product=product,
                        user=request.user,
                        current_stock=0,
                        alert_level=0
                    )
                
                if 'current_stock' in data:
                    old_stock = inventory.current_stock
                    new_stock = int(data['current_stock'])
                    
                    if old_stock != new_stock:
                        # Create inventory log for stock change
                        stock_change = new_stock - old_stock
                        log = InventoryLog.objects.create(
                            user=request.user,
                            product=product,
                            date=datetime.now(),
                            change=stock_change,
                            change_type=0,  # Other
                            description=f'Stock updated from {old_stock} to {new_stock} via AG Grid'
                        )
                        inventory.current_stock = new_stock
                        inventory.last_log = log
                        inventory_updated = True
                
                if 'alert_level' in data:
                    inventory.alert_level = int(data['alert_level'])
                    inventory_updated = True
                
                if inventory_updated:
                    inventory.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Product updated successfully',
                'product': {
                    'id': product.id,
                    'model_no': product.model_no,
                    'product_name': product.product_name,
                    'product_category_name': product.product_category.get_full_path() if product.product_category else '',
                    'parent_category': product.product_category.parent_category.category_name if product.product_category and product.product_category.parent_category else '',
                    'child_category': product.product_category.category_name if product.product_category else ''
                }
            })
            
        except Product.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Product not found'})
        except ProductCategory.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Category not found'})
        except ValueError as e:
            return JsonResponse({'success': False, 'error': f'Invalid value: {str(e)}'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})