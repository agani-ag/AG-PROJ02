# Django imports
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q
from django.core.paginator import Paginator
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
import datetime

# Model imports
from gstbillingapp.models import (
    Invoice, Customer, ReturnInvoice, UserProfile, 
    Product, Inventory, Book, BookLog
)

# Utility imports
from gstbillingapp.utility import (
    update_inventory_for_return,
    credit_customer_book_from_return,
    calculate_available_return_items,
    validate_return_data,
    get_next_return_invoice_number
)


@login_required
def return_invoices_list(request):
    """View all return invoices"""
    user_profile = request.user.userprofile
    
    # Get page size from request, default to 10
    page_size = request.GET.get('page_size', '10')
    try:
        page_size = int(page_size)
        if page_size not in [10, 25, 50, 100]:
            page_size = 10
    except ValueError:
        page_size = 10
    
    # Get all return invoices with optimized query
    return_invoices_list = ReturnInvoice.objects.filter(user=user_profile).select_related(
        'parent_invoice', 'customer'
    ).only(
        'id', 'return_invoice_number', 'return_date', 'return_type',
        'return_total_amt_with_gst', 'inventory_reflected', 'books_reflected',
        'parent_invoice__invoice_number', 'customer__customer_name'
    ).order_by('-return_date', '-return_invoice_number')
    
    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        return_invoices_list = return_invoices_list.filter(
            Q(return_invoice_number__icontains=search_query) |
            Q(customer__customer_name__icontains=search_query) |
            Q(parent_invoice__invoice_number__icontains=search_query)
        )
    
    # Pagination
    paginator = Paginator(return_invoices_list, page_size)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    context = {
        'return_invoices': page_obj,
        'page_obj': page_obj,
        'page_size': page_size,
        'search_query': search_query,
    }
    
    return render(request, 'returns/return_invoices.html', context)


@login_required
def return_invoice_create(request, invoice_id):
    """Create a return invoice for existing invoice"""
    user_profile = request.user.userprofile
    
    if request.method == 'GET':
        # Load parent invoice
        parent_invoice = get_object_or_404(Invoice, user=request.user, id=invoice_id)
        invoice_data = json.loads(parent_invoice.invoice_json)
        
        # Calculate available items for return (check previous returns)
        available_items = calculate_available_return_items(parent_invoice)
        
        # Check if any items are available for return
        has_available_items = any(
            item_info['available_qty'] > 0 
            for item_info in available_items.values()
        )
        
        context = {
            'parent_invoice': parent_invoice,
            'invoice_data': invoice_data,
            'available_items': available_items,
            'customer': parent_invoice.invoice_customer,
            'has_available_items': has_available_items,
            'today': datetime.date.today().strftime('%Y-%m-%d'),
        }
        return render(request, 'returns/return_invoice_create.html', context)
    
    elif request.method == 'POST':
        # Get parent invoice
        parent_invoice = get_object_or_404(Invoice, user=request.user, id=invoice_id)
        
        # Validate return data
        error = validate_return_data(request.POST, parent_invoice)
        if error:
            return JsonResponse({'status': 'error', 'message': error})
        
        try:
            # Process return items
            return_items = []
            total_without_gst = 0.0
            total_sgst = 0.0
            total_cgst = 0.0
            total_igst = 0.0
            
            invoice_data = json.loads(parent_invoice.invoice_json)
            is_igst = invoice_data.get('igstcheck', False)
            
            for idx, model_no in enumerate(request.POST.getlist('return-model-no')):
                if model_no:
                    return_qty = int(request.POST.getlist('return-qty')[idx])
                    if return_qty > 0:
                        # Find original item data
                        original_item = None
                        for item in invoice_data['items']:
                            # Check both invoice_product and invoice_model_no for compatibility
                            item_key = item.get('invoice_product', item.get('invoice_model_no', ''))
                            if item_key == model_no:
                                original_item = item
                                break
                        
                        if original_item:
                            # Calculate return amounts
                            rate_without_gst = float(original_item['invoice_rate_without_gst'])
                            gst_percentage = float(original_item['invoice_gst_percentage'])
                            
                            item_total_without_gst = rate_without_gst * return_qty
                            item_gst_amount = item_total_without_gst * (gst_percentage / 100)
                            
                            total_without_gst += item_total_without_gst
                            
                            if is_igst:
                                total_igst += item_gst_amount
                            else:
                                total_sgst += item_gst_amount / 2
                                total_cgst += item_gst_amount / 2
                            
                            return_items.append({
                                'invoice_model_no': model_no,
                                'invoice_product': original_item.get('invoice_product', original_item.get('invoice_model_no', model_no)),
                                'invoice_hsn': original_item.get('invoice_hsn', ''),
                                'return_qty': return_qty,
                                'original_qty': original_item.get('invoice_qty', 0),
                                'invoice_rate_with_gst': original_item.get('invoice_rate_with_gst', 0),
                                'invoice_rate_without_gst': original_item.get('invoice_rate_without_gst', 0),
                                'invoice_gst_percentage': original_item.get('invoice_gst_percentage', 0),
                                'invoice_discount': original_item.get('invoice_discount', 0.0)
                            })
            
            total_with_gst = total_without_gst + total_sgst + total_cgst + total_igst
            
            # Create return data JSON
            return_data = {
                'items': return_items,
                'return_total_amt_without_gst': round(total_without_gst, 2),
                'return_total_amt_sgst': round(total_sgst, 2),
                'return_total_amt_cgst': round(total_cgst, 2),
                'return_total_amt_igst': round(total_igst, 2),
                'return_total_amt_with_gst': round(total_with_gst, 2)
            }
            
            # Create ReturnInvoice object
            return_invoice = ReturnInvoice(
                user=user_profile,
                return_invoice_number=get_next_return_invoice_number(user_profile),
                return_date=request.POST.get('return-date'),
                parent_invoice=parent_invoice,
                customer=parent_invoice.invoice_customer,
                return_items_json=json.dumps(return_data),
                return_type=int(request.POST.get('return-type', 1)),
                return_total_amt_without_gst=return_data['return_total_amt_without_gst'],
                return_total_amt_sgst=return_data['return_total_amt_sgst'],
                return_total_amt_cgst=return_data['return_total_amt_cgst'],
                return_total_amt_igst=return_data['return_total_amt_igst'],
                return_total_amt_with_gst=return_data['return_total_amt_with_gst'],
                reason=request.POST.get('reason', ''),
                notes=request.POST.get('notes', '')
            )
            return_invoice.save()
            
            # Update inventory
            update_inventory_for_return(return_invoice, request)
            return_invoice.inventory_reflected = True
            return_invoice.save()
            
            # Credit customer book
            credit_customer_book_from_return(return_invoice)
            return_invoice.books_reflected = True
            return_invoice.save()
            
            return JsonResponse({
                'status': 'success',
                'message': 'Return invoice created successfully',
                'return_invoice_id': return_invoice.id,
                'redirect_url': f'/returns/{return_invoice.id}'
            })
            
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Error creating return invoice: {str(e)}'
            })


@login_required
def return_invoice_detail(request, return_id):
    """View return invoice details"""
    user_profile = request.user.userprofile
    return_invoice = get_object_or_404(ReturnInvoice, user=user_profile, id=return_id)
    return_data = json.loads(return_invoice.return_items_json)
    
    context = {
        'return_invoice': return_invoice,
        'return_data': return_data,
        'parent_invoice': return_invoice.parent_invoice,
        'customer': return_invoice.customer,
    }
    
    return render(request, 'returns/return_invoice_detail.html', context)


@login_required
@require_POST
def return_invoice_process(request, return_id):
    """Manually process incomplete return invoice updates"""
    user_profile = request.user.userprofile
    return_invoice = get_object_or_404(ReturnInvoice, user=user_profile, id=return_id)
    
    try:
        data = json.loads(request.body)
        process_type = data.get('process_type', 'all')
        
        messages = []
        
        # Process inventory if needed
        if process_type in ['inventory', 'all'] and not return_invoice.inventory_reflected:
            update_inventory_for_return(return_invoice, request)
            return_invoice.inventory_reflected = True
            messages.append('Inventory updated successfully')
        
        # Process books if needed
        if process_type in ['books', 'all'] and not return_invoice.books_reflected:
            credit_customer_book_from_return(return_invoice)
            return_invoice.books_reflected = True
            messages.append('Customer books updated successfully')
        
        return_invoice.save()
        
        if messages:
            return JsonResponse({
                'status': 'success',
                'message': '. '.join(messages)
            })
        else:
            return JsonResponse({
                'status': 'info',
                'message': 'No pending updates to process'
            })
            
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Error processing return: {str(e)}'
        })


@login_required
def return_invoice_printer(request, return_id):
    """Print return invoice"""
    user_profile = request.user.userprofile
    return_invoice = get_object_or_404(ReturnInvoice, user=user_profile, id=return_id)
    return_data = json.loads(return_invoice.return_items_json)
    
    # Get user profile details for printing
    from gstbillingapp.models import BankDetails
    bank_details = BankDetails.objects.filter(
        whom_account=0, 
        user=request.user
    ).first()
    
    context = {
        'return_invoice': return_invoice,
        'return_data': return_data,
        'parent_invoice': return_invoice.parent_invoice,
        'customer': return_invoice.customer,
        'user_profile': user_profile,
        'bank_details': bank_details,
    }
    
    return render(request, 'returns/return_invoice_printer.html', context)


@login_required
def return_invoice_delete(request, return_id):
    """Delete a return invoice and reverse all its effects"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'})
    
    try:
        user_profile = request.user.userprofile
        return_invoice = get_object_or_404(ReturnInvoice, id=return_id, user=user_profile)
        
        return_data = json.loads(return_invoice.return_items_json)
        customer = return_invoice.customer
        
        # Reverse inventory if it was reflected
        if return_invoice.inventory_reflected:
            for item in return_data:
                product_id = item.get('product_id')
                return_qty = float(item.get('return_qty', 0))
                
                if product_id and return_qty > 0:
                    try:
                        product = Product.objects.get(id=product_id, user=request.user)
                        inventory = Inventory.objects.get(product=product)
                        
                        # Reverse the inventory increase (subtract the returned quantity)
                        inventory.current_stock -= return_qty
                        inventory.save()
                    except (Product.DoesNotExist, Inventory.DoesNotExist):
                        pass  # Product or inventory might have been deleted
        
        # Reverse books if they were reflected
        if return_invoice.books_reflected:
            try:
                book = Book.objects.get(user=request.user, customer=customer)
                
                # Find and delete the associated book log
                book_logs = BookLog.objects.filter(
                    parent_book=book,
                    date=return_invoice.return_date,
                    change_type=3,  # 3 = Returned Items (correct type)
                    change=return_invoice.return_total_amt_with_gst
                ).order_by('-created_at')
                
                if book_logs.exists():
                    book_log = book_logs.first()
                    
                    # Reverse the credit (add back to customer debt)
                    book.current_balance -= return_invoice.return_total_amt_with_gst
                    
                    # Update last_log if this was the last entry
                    if book.last_log and book.last_log.id == book_log.id:
                        previous_log = BookLog.objects.filter(
                            parent_book=book
                        ).exclude(id=book_log.id).order_by('-date', '-created_at').first()
                        book.last_log = previous_log
                    
                    book.save()
                    book_log.delete()
                    
            except Book.DoesNotExist:
                pass  # Book might have been deleted
        
        # Delete the return invoice
        return_invoice.delete()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Return invoice deleted successfully'
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Error deleting return invoice: {str(e)}'
        })
