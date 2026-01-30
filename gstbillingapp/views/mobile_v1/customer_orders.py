# Django imports
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Max, Q
from django.db import transaction
from django.utils import timezone
from django.contrib.auth.models import User

# Models
from ...models import (
    Customer, Quotation, Product, UserProfile, Notification, ProductCategory
)

# Python imports
import json
import datetime
import num2words

# Utility functions
from ...utils import parse_code_GS


# ================= Customer Ordering System =============================

def customer_products_catalog(request):
    """Display products available for ordering"""
    context = {}
    cid = request.GET.get('cid', None)
    
    if not cid:
        return render(request, 'mobile_v1/orders/error.html', {
            'error': 'Invalid customer link'
        })
    
    # Parse customer ID from encoded string
    cid_data = parse_code_GS(cid)
    if not cid_data:
        return render(request, 'mobile_v1/orders/error.html', {
            'error': 'Invalid customer code'
        })
    
    customer_id = cid_data.get('C', None)
    user_id = cid_data.get('GS', None)
    
    try:
        customer = get_object_or_404(Customer, id=customer_id, user__id=user_id)
        business_user = customer.user
        user_profile = get_object_or_404(UserProfile, user=business_user)
        
        # Get category filter
        category_id = request.GET.get('category', '').strip()
        
        # Get all categories for filter dropdown
        categories = ProductCategory.objects.filter(user=business_user).order_by('category_name')
        
        # Get active products from business owner
        products = Product.objects.filter(user=business_user)
        
        # Apply category filter if specified
        if category_id and category_id.isdigit():
            products = products.filter(product_category_id=int(category_id))
        
        products = products.select_related('product_category').order_by('product_name')
        
        # Group products by category
        products_by_category = {}
        uncategorized_products = []
        
        for product in products:
            product_dict = {
                'id': product.id,
                'product_name': product.product_name,
                'model_no': product.model_no,
                'product_rate_with_gst': float(product.product_rate_with_gst),
                'product_gst_percentage': float(product.product_gst_percentage),
                'product_discount': float(product.product_discount or 0),
                'product_hsn': product.product_hsn,
                'product_image_url': product.product_image_url or '',
                'product_category': product.product_category.category_name if product.product_category else '',
                'product_category_id': product.product_category.id if product.product_category else None,
            }
            
            # Calculate discounted price
            if product.product_discount and product.product_discount > 0:
                discount_multiplier = 1 - (float(product.product_discount) / 100)
                product_dict['discounted_price'] = round(float(product.product_rate_with_gst) * discount_multiplier, 2)
            else:
                product_dict['discounted_price'] = float(product.product_rate_with_gst)
            
            # Group by category
            if product.product_category:
                category_name = product.product_category.category_name
                if category_name not in products_by_category:
                    products_by_category[category_name] = []
                products_by_category[category_name].append(product_dict)
            else:
                uncategorized_products.append(product_dict)
        
        context['customer'] = customer
        context['products_by_category'] = products_by_category
        context['uncategorized_products'] = uncategorized_products
        context['business_profile'] = user_profile
        context['cid'] = cid
        context['categories'] = categories
        context['selected_category'] = category_id
        
        return render(request, 'mobile_v1/orders/product_catalog.html', context)
    
    except Exception as e:
        return render(request, 'mobile_v1/orders/error.html', {
            'error': f'Error loading products: {str(e)}'
        })


def customer_create_order(request):
    """Customer creates a quotation (order request)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)
    
    try:
        cid = request.POST.get('cid')
        cid_data = parse_code_GS(cid)
        
        if not cid_data:
            return JsonResponse({'success': False, 'message': 'Invalid customer code'}, status=400)
        
        customer_id = cid_data.get('C', None)
        user_id = cid_data.get('GS', None)
        
        customer = get_object_or_404(Customer, id=customer_id, user__id=user_id)
        business_user = customer.user
        user_profile = get_object_or_404(UserProfile, user=business_user)
        
        # Parse order items
        order_items_json = request.POST.get('order_items', '[]')
        order_items = json.loads(order_items_json)
        
        if not order_items:
            return JsonResponse({'success': False, 'message': 'No items in order'}, status=400)
        
        # Determine if GST quotation
        is_gst = customer.customer_gst is not None and customer.customer_gst.strip() != ''
        
        # Get next quotation number
        max_quotation_number = Quotation.objects.filter(
            user=business_user, 
            is_gst=is_gst
        ).aggregate(Max('quotation_number'))['quotation_number__max']
        
        next_quotation_number = (max_quotation_number or 0) + 1
        
        # Build quotation JSON
        quotation_data = {
            'customer_name': customer.customer_name,
            'customer_address': customer.customer_address or '',
            'customer_phone': customer.customer_phone or '',
            'customer_gst': customer.customer_gst or '',
            'vehicle_number': '',
            'items': [],
            'igstcheck': False
        }
        
        total_amount_with_gst = 0
        total_amount_without_gst = 0
        total_sgst = 0
        total_cgst = 0
        total_igst = 0
        
        # Process each item
        for item in order_items:
            try:
                product = Product.objects.get(id=item['product_id'], user=business_user)
                quantity = int(item['quantity'])
                
                # Calculate amounts
                rate_with_gst = float(product.product_rate_with_gst)
                gst_percentage = float(product.product_gst_percentage)
                discount = float(product.product_discount or 0)
                
                # Calculate rate without GST
                rate_without_gst = rate_with_gst / (1 + (gst_percentage / 100))
                
                # Item total with GST
                item_total_with_gst = rate_with_gst * quantity
                item_total_without_gst = rate_without_gst * quantity
                
                # GST amounts
                gst_amount = item_total_with_gst - item_total_without_gst
                sgst_amount = gst_amount / 2
                cgst_amount = gst_amount / 2
                
                total_amount_with_gst += item_total_with_gst
                total_amount_without_gst += item_total_without_gst
                total_sgst += sgst_amount
                total_cgst += cgst_amount
                
                quotation_data['items'].append({
                    'invoice_model_no': product.model_no or '',
                    'invoice_product': product.product_name or '',
                    'invoice_hsn': product.product_hsn or '',
                    'invoice_qty': quantity,
                    'invoice_rate_with_gst': rate_with_gst,
                    'invoice_gst_percentage': gst_percentage,
                    'invoice_discount': discount,
                    'invoice_amt': item_total_with_gst
                })
            except Product.DoesNotExist:
                return JsonResponse({
                    'success': False, 
                    'message': f'Product not found'
                }, status=400)
        
        # Set totals
        quotation_data['invoice_total_amt_with_gst'] = round(total_amount_with_gst, 2)
        quotation_data['invoice_total_amt_without_gst'] = round(total_amount_without_gst, 2)
        quotation_data['invoice_total_amt_sgst'] = round(total_sgst, 2)
        quotation_data['invoice_total_amt_cgst'] = round(total_cgst, 2)
        quotation_data['invoice_total_amt_igst'] = round(total_igst, 2)
        
        # Create quotation
        valid_until = datetime.date.today() + datetime.timedelta(days=30)
        
        with transaction.atomic():
            new_quotation = Quotation(
                user=business_user,
                quotation_number=next_quotation_number,
                quotation_date=datetime.date.today(),
                valid_until=valid_until,
                quotation_customer=customer,
                quotation_json=json.dumps(quotation_data),
                is_gst=is_gst,
                status='DRAFT',
                created_by_customer=True,
                notes=f'Customer order via mobile app by {customer.customer_name}'
            )
            new_quotation.save()
            
            # Create notification for business owner
            notification = Notification(
                user=business_user,
                notification_type='ORDER',
                title=f'New Order from {customer.customer_name}',
                message=f'Order #{new_quotation.quotation_number} placed for ₹{total_amount_with_gst:.2f}',
                link_url=f'/quotation/{new_quotation.id}/',
                link_text='View Order'
            )
            notification.save()
            
            # Send WebSocket notification
            try:
                from asgiref.sync import async_to_sync
                from channels.layers import get_channel_layer
                
                channel_layer = get_channel_layer()
                if channel_layer:
                    async_to_sync(channel_layer.group_send)(
                        f"notifications_user_{business_user.id}",
                        {
                            'type': 'new_notification',
                            'notification': {
                                'id': notification.id,
                                'type': notification.notification_type,
                                'title': notification.title,
                                'message': notification.message,
                                'link_url': notification.link_url,
                                'link_text': notification.link_text,
                                'created_at': notification.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                            }
                        }
                    )
            except Exception as e:
                print(f"WebSocket notification failed: {e}")
        
        return JsonResponse({
            'success': True,
            'message': f'Order #{new_quotation.quotation_number} placed successfully!',
            'quotation_id': new_quotation.id,
            'quotation_number': new_quotation.quotation_number
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error creating order: {str(e)}'
        }, status=500)


def customer_orders_list(request):
    """List customer's own orders (quotations)"""
    context = {}
    cid = request.GET.get('cid', None)
    
    if not cid:
        return render(request, 'mobile_v1/orders/error.html', {
            'error': 'Invalid customer link'
        })
    
    cid_data = parse_code_GS(cid)
    if not cid_data:
        return render(request, 'mobile_v1/orders/error.html', {
            'error': 'Invalid customer code'
        })
    
    customer_id = cid_data.get('C', None)
    user_id = cid_data.get('GS', None)
    
    try:
        customer = get_object_or_404(Customer, id=customer_id, user__id=user_id)
        
        # Get all quotations for this customer (customer-initiated)
        quotations = Quotation.objects.filter(
            quotation_customer=customer,
            created_by_customer=True
        ).order_by('-created_at')
        
        # Parse quotation data for display
        quotations_list = []
        for quotation in quotations:
            try:
                quotation_data = json.loads(quotation.quotation_json)
                items = quotation_data.get('items', [])
                total_qty = sum(float(item.get('invoice_qty', 0)) for item in items)
                quotations_list.append({
                    'quotation': quotation,
                    'total_amount': quotation_data.get('invoice_total_amt_with_gst', 0),
                    'item_count': len(items),
                    'total_qty': total_qty
                })
            except:
                quotations_list.append({
                    'quotation': quotation,
                    'total_amount': 0,
                    'item_count': 0,
                    'total_qty': 0
                })
        
        context['customer'] = customer
        context['quotations_list'] = quotations_list
        context['cid'] = cid
        
        return render(request, 'mobile_v1/orders/orders_list.html', context)
    
    except Exception as e:
        return render(request, 'mobile_v1/orders/error.html', {
            'error': f'Error loading orders: {str(e)}'
        })


def customer_order_detail(request, quotation_id):
    """View customer order details"""
    context = {}
    cid = request.GET.get('cid', None)
    
    if not cid:
        return render(request, 'mobile_v1/orders/error.html', {
            'error': 'Invalid customer link'
        })
    
    cid_data = parse_code_GS(cid)
    if not cid_data:
        return render(request, 'mobile_v1/orders/error.html', {
            'error': 'Invalid customer code'
        })
    
    customer_id = cid_data.get('C', None)
    user_id = cid_data.get('GS', None)
    
    try:
        customer = get_object_or_404(Customer, id=customer_id, user__id=user_id)
        
        quotation = get_object_or_404(
            Quotation, 
            id=quotation_id,
            quotation_customer=customer
        )
        
        quotation_data = json.loads(quotation.quotation_json)
        
        # Process items to ensure discount calculation and invoice_amt
        for item in quotation_data.get('items', []):
            # Ensure invoice_discount field exists
            if 'invoice_discount' not in item:
                item['invoice_discount'] = 0
            
            # Calculate invoice_rate_after_discount if not present or if discount exists
            if item.get('invoice_discount', 0) > 0:
                if 'invoice_rate_after_discount' not in item or not item['invoice_rate_after_discount']:
                    rate_with_gst = float(item.get('invoice_rate_with_gst', 0))
                    discount_percent = float(item.get('invoice_discount', 0))
                    item['invoice_rate_after_discount'] = round(rate_with_gst * (1 - discount_percent / 100), 2)
                
                # Calculate invoice_amt using discounted rate
                if 'invoice_amt' not in item or not item['invoice_amt']:
                    qty = float(item.get('invoice_qty', 0))
                    item['invoice_amt'] = round(qty * item['invoice_rate_after_discount'], 2)
            else:
                # Calculate invoice_amt using regular rate if not present
                if 'invoice_amt' not in item or not item['invoice_amt']:
                    qty = float(item.get('invoice_qty', 0))
                    rate = float(item.get('invoice_rate_with_gst', 0))
                    item['invoice_amt'] = round(qty * rate, 2)
        
        user_profile = get_object_or_404(UserProfile, user=quotation.user)
        
        # Calculate total in words
        total_amount = quotation_data.get('invoice_total_amt_with_gst', 0)
        total_in_words = num2words.num2words(int(total_amount), lang='en_IN').title()
        
        # Calculate total quantity
        total_qty = sum(float(item.get('invoice_qty', 0)) for item in quotation_data.get('items', []))
        
        # Check if order can be edited (only DRAFT status and customer-created)
        can_edit = quotation.status == 'DRAFT' and quotation.created_by_customer
        
        context['customer'] = customer
        context['quotation'] = quotation
        context['quotation_data'] = quotation_data
        context['user_profile'] = user_profile
        context['total_in_words'] = total_in_words
        context['total_qty'] = total_qty
        context['currency'] = "₹"
        context['cid'] = cid
        context['can_edit'] = can_edit
        
        return render(request, 'mobile_v1/orders/order_detail.html', context)
    
    except Exception as e:
        return render(request, 'mobile_v1/orders/error.html', {
            'error': f'Error loading order: {str(e)}'
        })


def customer_edit_order(request, quotation_id):
    """Edit existing order - add/remove products (DRAFT only)"""
    context = {}
    cid = request.GET.get('cid', None)
    
    if not cid:
        return render(request, 'mobile_v1/orders/error.html', {
            'error': 'Invalid customer link'
        })
    
    cid_data = parse_code_GS(cid)
    if not cid_data:
        return render(request, 'mobile_v1/orders/error.html', {
            'error': 'Invalid customer code'
        })
    
    customer_id = cid_data.get('C', None)
    user_id = cid_data.get('GS', None)
    
    try:
        customer = get_object_or_404(Customer, id=customer_id, user__id=user_id)
        
        quotation = get_object_or_404(
            Quotation, 
            id=quotation_id,
            quotation_customer=customer,
            created_by_customer=True
        )
        
        # Check if order can be edited
        if quotation.status != 'DRAFT':
            return render(request, 'mobile_v1/orders/error.html', {
                'error': 'Order cannot be edited. Only DRAFT orders can be modified.'
            })
        
        business_user = customer.user
        user_profile = get_object_or_404(UserProfile, user=business_user)
        
        # Get all products with category relationship
        all_products = Product.objects.filter(user=business_user).select_related('product_category').order_by('product_name')
        
        # Parse existing order data
        quotation_data = json.loads(quotation.quotation_json)
        existing_items = quotation_data.get('items', [])
        
        # Create a map of existing products with quantities
        existing_products = {}
        existing_product_ids = []
        
        for item in existing_items:
            # Find product by model number and product name for better matching
            try:
                # Try to match by both model_no and product_name for uniqueness
                product = Product.objects.filter(
                    model_no=item['invoice_model_no'],
                    product_name=item['invoice_product'],
                    user=business_user
                ).first()
                
                # If no match with both, try just model_no
                if not product:
                    product = Product.objects.filter(
                        model_no=item['invoice_model_no'],
                        user=business_user
                    ).first()
                
                if product:
                    existing_products[product.id] = item['invoice_qty']
                    existing_product_ids.append(product.id)
            except Exception:
                continue
        
        # Separate products: existing first, then others
        products_in_order_qs = all_products.filter(id__in=existing_product_ids)
        products_not_in_order_qs = all_products.exclude(id__in=existing_product_ids)
        
        # Add discounted prices to products
        def add_discount_info(products_qs):
            products_list = []
            for product in products_qs:
                product_dict = {
                    'id': product.id,
                    'product_name': product.product_name,
                    'model_no': product.model_no,
                    'product_rate_with_gst': float(product.product_rate_with_gst),
                    'product_gst_percentage': float(product.product_gst_percentage),
                    'product_discount': float(product.product_discount or 0),
                    'product_hsn': product.product_hsn,
                    'product_image_url': product.product_image_url or '',
                    'product_category': product.product_category.category_name if product.product_category else '',
                }
                
                # Calculate discounted price
                if product.product_discount and product.product_discount > 0:
                    discount_multiplier = 1 - (float(product.product_discount) / 100)
                    product_dict['discounted_price'] = round(float(product.product_rate_with_gst) * discount_multiplier, 2)
                else:
                    product_dict['discounted_price'] = float(product.product_rate_with_gst)
                
                products_list.append(product_dict)
            return products_list
        
        def group_by_category(products_list):
            """Group products by category"""
            by_category = {}
            uncategorized = []
            
            for product in products_list:
                category_name = product.get('product_category', '')
                if category_name:
                    if category_name not in by_category:
                        by_category[category_name] = []
                    by_category[category_name].append(product)
                else:
                    uncategorized.append(product)
            
            return by_category, uncategorized
        
        products_in_order = add_discount_info(products_in_order_qs)
        products_not_in_order = add_discount_info(products_not_in_order_qs)
        
        # Group both lists by category
        products_in_order_by_category, uncategorized_in_order = group_by_category(products_in_order)
        products_not_in_order_by_category, uncategorized_not_in_order = group_by_category(products_not_in_order)
        
        context['customer'] = customer
        context['quotation'] = quotation
        context['products_in_order'] = products_in_order
        context['products_not_in_order'] = products_not_in_order
        context['products_in_order_by_category'] = products_in_order_by_category
        context['uncategorized_in_order'] = uncategorized_in_order
        context['products_not_in_order_by_category'] = products_not_in_order_by_category
        context['uncategorized_not_in_order'] = uncategorized_not_in_order
        context['business_profile'] = user_profile
        context['existing_products'] = existing_products
        context['cid'] = cid
        
        return render(request, 'mobile_v1/orders/order_edit.html', context)
    
    except Exception as e:
        return render(request, 'mobile_v1/orders/error.html', {
            'error': f'Error loading order for editing: {str(e)}'
        })


def customer_update_order(request, quotation_id):
    """Update existing order with new items (DRAFT only)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)
    
    try:
        cid = request.POST.get('cid')
        cid_data = parse_code_GS(cid)
        
        if not cid_data:
            return JsonResponse({'success': False, 'message': 'Invalid customer code'}, status=400)
        
        customer_id = cid_data.get('C', None)
        user_id = cid_data.get('GS', None)
        
        customer = get_object_or_404(Customer, id=customer_id, user__id=user_id)
        
        quotation = get_object_or_404(
            Quotation, 
            id=quotation_id,
            quotation_customer=customer,
            created_by_customer=True
        )
        
        # Check if order can be edited
        if quotation.status != 'DRAFT':
            return JsonResponse({
                'success': False, 
                'message': 'Order cannot be edited. Only DRAFT orders can be modified.'
            }, status=400)
        
        business_user = customer.user
        
        # Parse order items
        order_items_json = request.POST.get('order_items', '[]')
        order_items = json.loads(order_items_json)
        
        if not order_items:
            return JsonResponse({'success': False, 'message': 'No items in order'}, status=400)
        
        # Build updated quotation JSON
        quotation_data = {
            'customer_name': customer.customer_name,
            'customer_address': customer.customer_address or '',
            'customer_phone': customer.customer_phone or '',
            'customer_gst': customer.customer_gst or '',
            'vehicle_number': '',
            'items': [],
            'igstcheck': False
        }
        
        total_amount_with_gst = 0
        total_amount_without_gst = 0
        total_sgst = 0
        total_cgst = 0
        total_igst = 0
        
        # Process each item
        for item in order_items:
            try:
                product = Product.objects.get(id=item['product_id'], user=business_user)
                quantity = int(item['quantity'])
                
                # Calculate amounts
                rate_with_gst = float(product.product_rate_with_gst)
                gst_percentage = float(product.product_gst_percentage)
                discount = float(product.product_discount or 0)
                
                # Calculate rate without GST
                rate_without_gst = rate_with_gst / (1 + (gst_percentage / 100))
                
                # Item total with GST
                item_total_with_gst = rate_with_gst * quantity
                item_total_without_gst = rate_without_gst * quantity
                
                # GST amounts
                gst_amount = item_total_with_gst - item_total_without_gst
                sgst_amount = gst_amount / 2
                cgst_amount = gst_amount / 2
                
                total_amount_with_gst += item_total_with_gst
                total_amount_without_gst += item_total_without_gst
                total_sgst += sgst_amount
                total_cgst += cgst_amount
                
                quotation_data['items'].append({
                    'invoice_model_no': product.model_no or '',
                    'invoice_product': product.product_name or '',
                    'invoice_hsn': product.product_hsn or '',
                    'invoice_qty': quantity,
                    'invoice_rate_with_gst': rate_with_gst,
                    'invoice_gst_percentage': gst_percentage,
                    'invoice_discount': discount,
                    'invoice_amt': item_total_with_gst
                })
            except Product.DoesNotExist:
                return JsonResponse({
                    'success': False, 
                    'message': f'Product not found'
                }, status=400)
        
        # Set totals
        quotation_data['invoice_total_amt_with_gst'] = round(total_amount_with_gst, 2)
        quotation_data['invoice_total_amt_without_gst'] = round(total_amount_without_gst, 2)
        quotation_data['invoice_total_amt_sgst'] = round(total_sgst, 2)
        quotation_data['invoice_total_amt_cgst'] = round(total_cgst, 2)
        quotation_data['invoice_total_amt_igst'] = round(total_igst, 2)
        
        # Update quotation
        with transaction.atomic():
            quotation.quotation_json = json.dumps(quotation_data)
            quotation.updated_at = timezone.now()
            quotation.save()
            
            # Create notification for business owner
            notification = Notification(
                user=business_user,
                notification_type='ORDER',
                title=f'Order Updated by {customer.customer_name}',
                message=f'Order #{quotation.quotation_number} updated to ₹{total_amount_with_gst:.2f}',
                link_url=f'/quotation/{quotation.id}/',
                link_text='View Order'
            )
            notification.save()
            
            # Send WebSocket notification
            try:
                from asgiref.sync import async_to_sync
                from channels.layers import get_channel_layer
                
                channel_layer = get_channel_layer()
                if channel_layer:
                    async_to_sync(channel_layer.group_send)(
                        f"notifications_user_{business_user.id}",
                        {
                            'type': 'new_notification',
                            'notification': {
                                'id': notification.id,
                                'type': notification.notification_type,
                                'title': notification.title,
                                'message': notification.message,
                                'link_url': notification.link_url,
                                'link_text': notification.link_text,
                                'created_at': notification.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                            }
                        }
                    )
            except Exception as e:
                print(f"WebSocket notification failed: {e}")
        
        return JsonResponse({
            'success': True,
            'message': f'Order #{quotation.quotation_number} updated successfully!',
            'quotation_id': quotation.id,
            'quotation_number': quotation.quotation_number
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error updating order: {str(e)}'
        }, status=500)


def customer_delete_order(request, quotation_id):
    """Delete customer order (DRAFT only)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)
    
    try:
        cid = request.POST.get('cid')
        cid_data = parse_code_GS(cid)
        
        if not cid_data:
            return JsonResponse({'success': False, 'message': 'Invalid customer code'}, status=400)
        
        customer_id = cid_data.get('C', None)
        user_id = cid_data.get('GS', None)
        
        customer = get_object_or_404(Customer, id=customer_id, user__id=user_id)
        
        quotation = get_object_or_404(
            Quotation, 
            id=quotation_id,
            quotation_customer=customer,
            created_by_customer=True
        )
        
        # Check if order can be deleted (only DRAFT status)
        if quotation.status != 'DRAFT':
            return JsonResponse({
                'success': False, 
                'message': 'Only pending orders can be deleted.'
            }, status=400)
        
        # Delete the quotation
        quotation_number = quotation.quotation_number
        quotation.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'Order #{quotation_number} has been deleted successfully.'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error: {str(e)}'})


def customer_order_received(request, quotation_id):
    """Mark order as received by customer"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)
    
    try:
        cid = request.POST.get('cid')
        cid_data = parse_code_GS(cid)
        
        if not cid_data:
            return JsonResponse({'success': False, 'message': 'Invalid customer code'}, status=400)
        
        customer_id = cid_data.get('C', None)
        user_id = cid_data.get('GS', None)
        
        customer = get_object_or_404(Customer, id=customer_id, user__id=user_id)
        
        quotation = get_object_or_404(
            Quotation, 
            id=quotation_id,
            quotation_customer=customer,
            created_by_customer=True
        )
        
        # Check if order is delivered
        if quotation.status != 'DELIVERED':
            return JsonResponse({
                'success': False, 
                'message': 'Only delivered orders can be marked as received.'
            }, status=400)
        
        # Update status to CONVERTED (completed)
        quotation.status = 'CONVERTED'
        quotation.save()
        
        # Create notification for business owner
        try:
            Notification.objects.create(
                user=quotation.user,
                notification_type='ORDER',
                title=f'Order #{quotation.quotation_number} Received',
                message=f'{customer.customer_name} has confirmed receipt of Order #{quotation.quotation_number}',
                reference_id=quotation.id,
                reference_type='quotation'
            )
        except:
            pass  # Notification is optional
        
        return JsonResponse({
            'success': True,
            'message': 'Thank you for confirming receipt! Order marked as completed.'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error: {str(e)}'})
