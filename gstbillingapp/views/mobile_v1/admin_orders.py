# Django imports
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q, Sum, Count
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.db import transaction
from datetime import datetime, timedelta
import num2words
import json

# Local imports
from ...models import Quotation, Customer, Product, Invoice, Inventory, InventoryLog, UserProfile


@login_required
def admin_orders_list(request):
    """Admin view for managing all orders"""
    user = request.user
    
    # Get filter parameters
    status_filter = request.GET.get('status', 'all')
    users_filter = request.GET.get('users_filter', None)  # None means not provided
    user_ids = []
    
    # Get all users for dropdown
    users = UserProfile.objects.all().select_related('user').order_by('business_title')
    
    # Base queryset - Admin mode defaults to showing ALL orders
    if users_filter is None or users_filter == '':
        # No filter OR empty string - show ALL orders (admin default)
        queryset = Quotation.objects.all().select_related('quotation_customer', 'user', 'converted_invoice')
    else:
        # Specific user IDs provided - filter by those users
        user_ids = [int(uid) for uid in users_filter.split(',') if uid.isdigit()]
        users = users.filter(user__id__in=user_ids)
        queryset = Quotation.objects.filter(user__id__in=user_ids).select_related('quotation_customer', 'user', 'converted_invoice')
    
    # Apply status filter
    if status_filter and status_filter != 'all':
        queryset = queryset.filter(status=status_filter.upper())
    
    # Order by latest first
    queryset = queryset.order_by('-quotation_date', '-id')
    
    # Get all quotations with calculated totals
    quotations_list = []
    for quotation in queryset[:50]:  # Limit to 50 for performance
        try:
            quotation_data = json.loads(quotation.quotation_json)
            
            total_amount = float(quotation_data.get('invoice_total_amt_with_gst', 0))
            total_qty = sum(float(item.get('invoice_qty', 0)) for item in quotation_data.get('items', []))
            item_count = len(quotation_data.get('items', []))
            
            customer_name = "Unknown Customer"
            if quotation.quotation_customer:
                customer_name = quotation.quotation_customer.customer_name
            elif quotation_data.get('customer_name'):
                customer_name = quotation_data.get('customer_name')
            
            # Get business brand/title
            business_brand = "Unknown Brand"
            try:
                user_profile = UserProfile.objects.get(user=quotation.user)
                business_brand = user_profile.business_brand or user_profile.user.username
            except UserProfile.DoesNotExist:
                business_brand = quotation.user.username
            
            quotations_list.append({
                'quotation': quotation,
                'total_amount': total_amount,
                'total_qty': total_qty,
                'item_count': item_count,
                'customer_name': customer_name,
                'business_brand': business_brand
            })
        except Exception as e:
            print(f"Error processing quotation {quotation.id}: {e}")
            continue
    
    # Get status counts for summary cards
    status_counts = {}
    for status_choice in Quotation.STATUS_CHOICES:
        status_code = status_choice[0]
        if users_filter is None or users_filter == '':
            # No filter OR empty string - show ALL orders count (admin default)
            count = Quotation.objects.filter(status=status_code).count()
        else:
            # Filter by specific user IDs
            count = Quotation.objects.filter(user__id__in=user_ids, status=status_code).count()
        status_counts[status_code] = count
    
    # Processing count (sum of PROCESSING + PACKED + SHIPPED + OUT_FOR_DELIVERY)
    processing_count = (
        status_counts.get('PROCESSING', 0) + 
        status_counts.get('PACKED', 0) + 
        status_counts.get('SHIPPED', 0) + 
        status_counts.get('OUT_FOR_DELIVERY', 0)
    )
    
    context = {
        'quotations_list': quotations_list,
        'status_counts': status_counts,
        'processing_count': processing_count,
        'current_filter': status_filter,
        'has_more': len(queryset) > 50,
        'users': users,
        'users_filter': users_filter,
    }
    
    return render(request, 'mobile_v1/admin/admin_orders_list.html', context)


@login_required
def admin_order_detail(request, quotation_id):
    """Admin view for order details"""
    users_filter = request.GET.get('users_filter', None)  # None means not provided
    
    # Get quotation - Admin mode allows ALL orders by default
    quotation = get_object_or_404(Quotation, id=quotation_id)
    
    # Apply user filter ONLY if specific user IDs provided (not None, not empty)
    if users_filter and users_filter != '':
        # Specific user IDs provided - check if quotation user is in the list
        user_ids = [int(uid) for uid in users_filter.split(',') if uid.isdigit()]
        if quotation.user.id not in user_ids:
            return render(request, 'mobile_v1/orders/error.html', {
                'error_message': 'Order not found or access denied.'
            })
    # else: No filter (None) or empty string - allow ALL orders (admin mode)
    
    # Use quotation's user for operations
    user = quotation.user
    
    try:
        quotation_data = json.loads(quotation.quotation_json)
    except Exception as e:
        return render(request, 'mobile_v1/orders/error.html', {
            'error_message': f'Error loading order data: {e}'
        })
    
    # Calculate total quantity
    total_qty = sum(float(item.get('invoice_qty', 0)) for item in quotation_data.get('items', []))
    
    # Get amount in words
    total_amount = float(quotation_data.get('invoice_total_amt_with_gst', 0))
    total_in_words = num2words.num2words(total_amount)
    
    # Get user profile
    try:
        user_profile = UserProfile.objects.get(user=user)
    except UserProfile.DoesNotExist:
        user_profile = None
    
    context = {
        'quotation': quotation,
        'quotation_data': quotation_data,
        'total_qty': total_qty,
        'total_in_words': total_in_words,
        'user_profile': user_profile,
        'currency': '₹',
    }
    
    return render(request, 'mobile_v1/admin/admin_order_detail.html', context)


@login_required
def admin_order_edit(request, quotation_id):
    """Admin mobile view for editing orders"""
    users_filter = request.GET.get('users_filter', None)
    
    # Get quotation - Admin mode allows ALL orders by default
    quotation = get_object_or_404(Quotation, id=quotation_id)
    
    # Apply user filter only if specific user IDs provided
    if users_filter and users_filter != '':
        # Specific user IDs - check access
        user_ids = [int(uid) for uid in users_filter.split(',') if uid.isdigit()]
        if quotation.user.id not in user_ids:
            return render(request, 'mobile_v1/orders/error.html', {
                'error_message': 'Order not found or access denied.'
            })
    # else: No filter or empty string - allow ALL orders (admin mode)
    
    # Use quotation's user for product filtering
    user = quotation.user
    
    # Check if can be edited
    if not quotation.can_be_edited():
        return render(request, 'mobile_v1/orders/error.html', {
            'error_message': 'This order cannot be edited. It may have been converted to an invoice.'
        })
    
    # Check if order is in DRAFT status
    if quotation.status != 'DRAFT':
        return render(request, 'mobile_v1/orders/error.html', {
            'error_message': f'Order cannot be edited. Only DRAFT orders can be modified. Current status: {quotation.get_status_display()}'
        })
    
    try:
        user_profile = get_object_or_404(UserProfile, user=user)
        
        # Get all products with category relationship including parent
        all_products = Product.objects.filter(user=user).select_related(
            'product_category', 'product_category__parent_category'
        ).order_by(
            'product_category__parent_category__category_name',
            'product_category__category_name',
            'product_name'
        )
        
        # Parse existing order data
        quotation_data = json.loads(quotation.quotation_json)
        existing_items = quotation_data.get('items', [])
        
        # Create a map of existing products with quantities, prices, and discounts
        existing_products = {}
        existing_product_ids = []
        custom_pricing = {}  # Store custom prices and discounts
        
        for item in existing_items:
            model_no = item.get('invoice_model_no', '')
            if model_no:
                existing_products[model_no] = {
                    'qty': float(item.get('invoice_qty', 0)),
                    'rate': float(item.get('invoice_rate', 0)),
                    'discount': float(item.get('invoice_discount', 0))
                }
                # Find product ID
                product = all_products.filter(model_no=model_no).first()
                if product:
                    existing_product_ids.append(product.id)
                    # Store custom pricing by product ID
                    custom_pricing[product.id] = {
                        'rate': float(item.get('invoice_rate', 0)),
                        'discount': float(item.get('invoice_discount', 0))
                    }
        
        # Separate products into in-order and not-in-order
        products_in_order = all_products.filter(id__in=existing_product_ids)
        products_not_in_order = all_products.exclude(id__in=existing_product_ids)
        
        # Helper function to organize products by hierarchical category
        def organize_by_category(products_qs):
            organized = {}
            for product in products_qs:
                # Check if there's custom pricing for this product
                if product.id in custom_pricing:
                    rate = custom_pricing[product.id]['rate']
                    discount = custom_pricing[product.id]['discount']
                    # Update product attributes to show custom values
                    product.product_rate_with_gst = rate
                    product.product_discount = discount
                else:
                    rate = float(product.product_rate_with_gst or 0)
                    discount = float(product.product_discount or 0)
                
                discounted_price = rate * (1 - discount / 100)
                product.discounted_price = discounted_price
                
                # Set initial quantity if in order
                product_data = existing_products.get(product.model_no, {})
                product.initial_qty = product_data.get('qty', 0) if isinstance(product_data, dict) else product_data
                
                if product.product_category:
                    parent_name = product.product_category.parent_category.category_name if product.product_category.parent_category else "Uncategorized"
                    child_name = product.product_category.category_name
                    
                    if parent_name not in organized:
                        organized[parent_name] = {}
                    if child_name not in organized[parent_name]:
                        organized[parent_name][child_name] = []
                    organized[parent_name][child_name].append(product)
            return organized
        
        products_in_order_by_category = organize_by_category(products_in_order)
        products_not_in_order_by_category = organize_by_category(products_not_in_order)
        
        # Uncategorized products
        uncategorized_in_order = products_in_order.filter(product_category__isnull=True)
        uncategorized_not_in_order = products_not_in_order.filter(product_category__isnull=True)
        
        # Add discounted price and initial qty for uncategorized
        for product in uncategorized_in_order:
            # Check if there's custom pricing for this product
            if product.id in custom_pricing:
                rate = custom_pricing[product.id]['rate']
                discount = custom_pricing[product.id]['discount']
                product.product_rate_with_gst = rate
                product.product_discount = discount
            else:
                rate = float(product.product_rate_with_gst or 0)
                discount = float(product.product_discount or 0)
            
            product.discounted_price = rate * (1 - discount / 100)
            product_data = existing_products.get(product.model_no, {})
            product.initial_qty = product_data.get('qty', 0) if isinstance(product_data, dict) else product_data
        
        for product in uncategorized_not_in_order:
            rate = float(product.product_rate_with_gst or 0)
            discount = float(product.product_discount or 0)
            product.discounted_price = rate * (1 - discount / 100)
            product.initial_qty = 0
        
        context = {
            'quotation': quotation,
            'user_profile': user_profile,
            'products_in_order': products_in_order,
            'products_not_in_order': products_not_in_order,
            'products_in_order_by_category': products_in_order_by_category,
            'products_not_in_order_by_category': products_not_in_order_by_category,
            'uncategorized_in_order': uncategorized_in_order,
            'uncategorized_not_in_order': uncategorized_not_in_order,
            'is_admin_edit': True,  # Flag to indicate admin editing
        }
        
        return render(request, 'mobile_v1/admin/admin_order_edit.html', context)
        
    except Exception as e:
        return render(request, 'mobile_v1/orders/error.html', {
            'error_message': f'Error loading order for editing: {str(e)}'
        })


@login_required
@require_POST
def admin_order_update_status(request, quotation_id):
    """Update order status"""
    users_filter = request.POST.get('users_filter', None)
    
    # Get quotation - Admin mode allows ALL orders by default
    quotation = get_object_or_404(Quotation, id=quotation_id)
    
    # Apply user filter only if specific user IDs provided
    if users_filter and users_filter != '':
        # Specific user IDs - check access
        user_ids = [int(uid) for uid in users_filter.split(',') if uid.isdigit()]
        if quotation.user.id not in user_ids:
            return JsonResponse({
                'success': False,
                'message': 'Order not found or access denied.'
            })
    # else: No filter or empty string - allow ALL orders (admin mode)
    
    new_status = request.POST.get('new_status', '').upper()
    
    # Validate status
    valid_statuses = [choice[0] for choice in Quotation.STATUS_CHOICES]
    if new_status not in valid_statuses:
        return JsonResponse({
            'success': False,
            'message': 'Invalid status'
        })
    
    # Don't allow changing from CONVERTED
    if quotation.status == 'CONVERTED':
        return JsonResponse({
            'success': False,
            'message': 'Cannot change status of converted orders'
        })
    
    # Update status
    quotation.status = new_status
    quotation.save()
    
    # Get status display name
    status_display = dict(Quotation.STATUS_CHOICES).get(new_status, new_status)
    
    return JsonResponse({
        'success': True,
        'message': f'Order status updated to: {status_display}',
        'new_status': new_status
    })


@login_required
@require_POST
def admin_order_convert_to_invoice(request, quotation_id):
    """Convert quotation to invoice"""
    users_filter = request.POST.get('users_filter', None)
    
    # Get quotation - Admin mode allows ALL orders by default
    quotation = get_object_or_404(Quotation, id=quotation_id)
    
    # Apply user filter only if specific user IDs provided
    if users_filter and users_filter != '':
        # Specific user IDs - check access
        user_ids = [int(uid) for uid in users_filter.split(',') if uid.isdigit()]
        if quotation.user.id not in user_ids:
            return JsonResponse({
                'success': False,
                'message': 'Order not found or access denied.'
            })
    # else: No filter or empty string - allow ALL orders (admin mode)
    
    # Use quotation's user for invoice operations
    user = quotation.user
    
    # Check if can be converted
    if not quotation.can_be_converted():
        return JsonResponse({
            'success': False,
            'message': 'This order cannot be converted to invoice'
        })
    
    # Get optional notes from request
    additional_notes = request.POST.get('notes', '')
    
    try:
        with transaction.atomic():
            # Parse quotation data
            quotation_data = json.loads(quotation.quotation_json)
            
            # Get next invoice number
            last_invoice = Invoice.objects.filter(user=user).order_by('-invoice_number').first()
            next_invoice_number = (last_invoice.invoice_number + 1) if last_invoice else 1
            
            # Add notes to quotation data if provided
            if additional_notes:
                if quotation_data.get('notes'):
                    quotation_data['notes'] = f"{quotation_data['notes']}\n\n{additional_notes}"
                else:
                    quotation_data['notes'] = additional_notes
            
            # Create invoice
            invoice = Invoice.objects.create(
                user=user,
                invoice_number=next_invoice_number,
                invoice_date=timezone.now().date(),
                invoice_customer=quotation.quotation_customer,
                invoice_json=json.dumps(quotation_data),
                is_gst=quotation.is_gst
            )
            
            # Update inventory for each item
            for item in quotation_data.get('items', []):
                product_model = item.get('invoice_model_no')
                qty = float(item.get('invoice_qty', 0))
                
                if product_model and qty > 0:
                    try:
                        product = Product.objects.filter(user=user, model_no=product_model).first()
                        if product:
                            # Get or create inventory
                            inventory = Inventory.objects.filter(product=product, user=user).first()
                            if inventory:
                                old_stock = inventory.current_stock
                                inventory.current_stock -= qty
                                inventory.save()
                                
                                # Create inventory log
                                InventoryLog.objects.create(
                                    inventory=inventory,
                                    change_type=1,  # Sale/Outward
                                    change_amount=-qty,
                                    description=f'Invoice #{next_invoice_number} - Order #{quotation.quotation_number}'
                                )
                    except Exception as e:
                        print(f"Error updating inventory for {product_model}: {e}")
            
            # Update quotation
            quotation.status = 'CONVERTED'
            quotation.converted_invoice = invoice
            quotation.converted_at = timezone.now()
            quotation.converted_by = user
            quotation.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Order successfully converted to invoice',
                'invoice_number': invoice.invoice_number,
                'invoice_url': reverse('invoice_viewer', args=[invoice.id])
            })
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error converting to invoice: {str(e)}'
        })


@login_required
@require_POST
def admin_order_update(request, quotation_id):
    """Admin endpoint for updating order items"""
    users_filter = request.POST.get('users_filter', None)
    
    try:
        # Get quotation - Admin mode allows ALL orders by default
        quotation = get_object_or_404(Quotation, id=quotation_id)
        
        # Apply user filter only if specific user IDs provided
        if users_filter and users_filter != '':
            # Specific user IDs - check access
            user_ids = [int(uid) for uid in users_filter.split(',') if uid.isdigit()]
            if quotation.user.id not in user_ids:
                return JsonResponse({
                    'success': False,
                    'message': 'Order not found or access denied.'
                })
        # else: No filter or empty string - allow ALL orders (admin mode)
        
        # Use quotation's user for operations
        user = quotation.user
        
        # Check if order can be edited
        if not quotation.can_be_edited():
            return JsonResponse({
                'success': False,
                'message': 'This order cannot be edited. It may have been converted to an invoice.'
            })
        
        # Check if status is DRAFT
        if quotation.status != 'DRAFT':
            return JsonResponse({
                'success': False,
                'message': f'Only DRAFT orders can be edited. Current status: {quotation.get_status_display()}'
            })
        
        # Get order items from request
        order_items_json = request.POST.get('order_items')
        if not order_items_json:
            return JsonResponse({
                'success': False,
                'message': 'No order items provided'
            })
        
        order_items = json.loads(order_items_json)
        
        if not order_items:
            return JsonResponse({
                'success': False,
                'message': 'Order must have at least one item'
            })
        
        # Parse existing quotation data
        try:
            quotation_data = json.loads(quotation.quotation_json)
        except:
            quotation_data = {}
        
        # Get user profile for business info
        user_profile = get_object_or_404(UserProfile, user=user)
        
        # Build updated items list with product details
        updated_items = []
        subtotal = 0
        total_gst = 0
        
        for item in order_items:
            product_id = item.get('product_id')
            quantity = float(item.get('quantity', 0))
            
            if quantity <= 0:
                continue
            
            try:
                product = Product.objects.get(id=product_id, user=user)
                
                # Check if custom price/discount provided (admin edit)
                custom_rate = item.get('rate')
                custom_discount = item.get('discount')
                
                if custom_rate is not None and custom_discount is not None:
                    # Use custom pricing from admin
                    rate = float(custom_rate)
                    discount = float(custom_discount)
                else:
                    # Use product default pricing
                    rate = float(product.product_rate_with_gst or 0)
                    discount = float(product.product_discount or 0)
                
                discounted_rate = rate * (1 - discount / 100)
                
                # Calculate amounts
                amount = discounted_rate * quantity
                
                # GST calculation (rate is with GST, need to extract GST amount)
                gst_percentage = float(product.product_gst_percentage or 0)
                rate_without_gst = discounted_rate / (1 + gst_percentage / 100)
                gst_amount = (rate_without_gst * gst_percentage / 100) * quantity
                
                subtotal += amount
                total_gst += gst_amount
                
                # Build item data
                item_data = {
                    'invoice_product_name': product.product_name,
                    'invoice_model_no': product.model_no,
                    'invoice_hsn': product.product_hsn or '',
                    'invoice_qty': quantity,
                    'invoice_rate': rate,
                    'invoice_discount': discount,
                    'invoice_discounted_rate': discounted_rate,
                    'invoice_gst_percentage': gst_percentage,
                    'invoice_gst_amount': round(gst_amount, 2),
                    'invoice_amt': round(amount, 2)
                }
                
                updated_items.append(item_data)
                
            except Product.DoesNotExist:
                continue
        
        if not updated_items:
            return JsonResponse({
                'success': False,
                'message': 'No valid products found in order'
            })
        
        # Update quotation data
        quotation_data['items'] = updated_items
        quotation_data['invoice_sub_total'] = round(subtotal, 2)
        quotation_data['invoice_total_gst'] = round(total_gst, 2)
        quotation_data['invoice_total_amt_with_gst'] = round(subtotal, 2)
        
        # Keep existing customer and business info
        if 'customer_name' not in quotation_data and quotation.quotation_customer:
            quotation_data['customer_name'] = quotation.quotation_customer.customer_name
            quotation_data['customer_address'] = quotation.quotation_customer.customer_address or ''
            quotation_data['customer_phone'] = quotation.quotation_customer.customer_phone or ''
            quotation_data['customer_gst'] = quotation.quotation_customer.customer_gst or ''
        
        if 'business_name' not in quotation_data:
            quotation_data['business_name'] = user_profile.business_title or ''
            quotation_data['business_address'] = user_profile.business_address or ''
            quotation_data['business_phone'] = user_profile.business_phone or ''
            quotation_data['business_gst'] = user_profile.business_gst or ''
        
        # Save updated quotation
        quotation.quotation_json = json.dumps(quotation_data)
        quotation.customer_details_modified = True
        quotation.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Order updated successfully'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error updating order: {str(e)}'
        })
