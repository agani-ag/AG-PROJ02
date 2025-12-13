# Django imports
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q, Sum
import datetime

# Model imports
from gstbillingapp.models import (
    Customer, CustomerPayment, CustomerDiscount, 
    Book, BookLog, UserProfile
)


@login_required
def customer_payments_list(request):
    """View all customer payments"""
    user_profile = request.user.userprofile
    
    # Get all payments
    payments = CustomerPayment.objects.filter(user=user_profile).select_related(
        'customer', 'book_log'
    ).order_by('-payment_date', '-created_at')
    
    # Filter by customer if specified
    customer_id = request.GET.get('customer_id')
    if customer_id:
        payments = payments.filter(customer_id=customer_id)
    
    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        payments = payments.filter(
            Q(customer__customer_name__icontains=search_query) |
            Q(reference_number__icontains=search_query) |
            Q(notes__icontains=search_query)
        )
    
    # Calculate totals
    total_amount = payments.aggregate(Sum('amount'))['amount__sum'] or 0
    
    context = {
        'payments': payments,
        'search_query': search_query,
        'total_amount': total_amount,
    }
    
    return render(request, 'payments/customer_payments.html', context)


@login_required
def customer_payment_add(request, customer_id=None):
    """Add customer payment"""
    user_profile = request.user.userprofile
    
    if request.method == 'GET':
        # Get all customers
        customers = Customer.objects.filter(user=request.user).order_by('customer_name')
        
        # Pre-select customer if provided
        selected_customer = None
        if customer_id:
            selected_customer = get_object_or_404(Customer, user=request.user, id=customer_id)
        
        context = {
            'customers': customers,
            'selected_customer': selected_customer,
            'today': datetime.date.today().strftime('%Y-%m-%d'),
            'payment_modes': CustomerPayment.PAYMENT_MODES,
        }
        
        return render(request, 'payments/customer_payment_add.html', context)
    
    elif request.method == 'POST':
        try:
            # Validate data
            customer_id = request.POST.get('customer_id')
            payment_date = request.POST.get('payment_date')
            amount = float(request.POST.get('amount'))
            payment_mode = int(request.POST.get('payment_mode'))
            
            if not customer_id or not payment_date or amount <= 0:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Please provide valid customer, date, and amount'
                })
            
            customer = get_object_or_404(Customer, user=request.user, id=customer_id)
            
            # Create payment record
            payment = CustomerPayment(
                user=user_profile,
                customer=customer,
                payment_date=payment_date,
                amount=amount,
                payment_mode=payment_mode,
                reference_number=request.POST.get('reference_number', ''),
                notes=request.POST.get('notes', '')
            )
            payment.save()  # This will auto-create BookLog via model's save method
            
            return JsonResponse({
                'status': 'success',
                'message': 'Payment recorded successfully',
                'redirect_url': '/customers/payments'
            })
            
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Error recording payment: {str(e)}'
            })


@login_required
def customer_discounts_list(request):
    """View all customer discounts"""
    user_profile = request.user.userprofile
    
    # Get all discounts
    discounts = CustomerDiscount.objects.filter(user=user_profile).select_related(
        'customer', 'book_log'
    ).order_by('-discount_date', '-created_at')
    
    # Filter by customer if specified
    customer_id = request.GET.get('customer_id')
    if customer_id:
        discounts = discounts.filter(customer_id=customer_id)
    
    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        discounts = discounts.filter(
            Q(customer__customer_name__icontains=search_query) |
            Q(reason__icontains=search_query) |
            Q(notes__icontains=search_query)
        )
    
    # Calculate totals
    total_amount = discounts.aggregate(Sum('amount'))['amount__sum'] or 0
    
    context = {
        'discounts': discounts,
        'search_query': search_query,
        'total_amount': total_amount,
    }
    
    return render(request, 'discounts/customer_discounts.html', context)


@login_required
def customer_discount_add(request, customer_id=None):
    """Add customer discount"""
    user_profile = request.user.userprofile
    
    if request.method == 'GET':
        # Get all customers
        customers = Customer.objects.filter(user=request.user).order_by('customer_name')
        
        # Pre-select customer if provided
        selected_customer = None
        if customer_id:
            selected_customer = get_object_or_404(Customer, user=request.user, id=customer_id)
        
        context = {
            'customers': customers,
            'selected_customer': selected_customer,
            'today': datetime.date.today().strftime('%Y-%m-%d'),
            'discount_types': CustomerDiscount.DISCOUNT_TYPES,
        }
        
        return render(request, 'discounts/customer_discount_add.html', context)
    
    elif request.method == 'POST':
        try:
            # Validate data
            customer_id = request.POST.get('customer_id')
            discount_date = request.POST.get('discount_date')
            amount = float(request.POST.get('amount'))
            discount_type = int(request.POST.get('discount_type'))
            reason = request.POST.get('reason', '').strip()
            
            if not customer_id or not discount_date or amount <= 0:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Please provide valid customer, date, and amount'
                })
            
            if not reason:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Please provide a reason for the discount'
                })
            
            customer = get_object_or_404(Customer, user=request.user, id=customer_id)
            
            # Create discount record
            discount = CustomerDiscount(
                user=user_profile,
                customer=customer,
                discount_date=discount_date,
                amount=amount,
                discount_type=discount_type,
                reason=reason,
                notes=request.POST.get('notes', '')
            )
            discount.save()  # This will auto-create BookLog via model's save method
            
            return JsonResponse({
                'status': 'success',
                'message': 'Discount recorded successfully',
                'redirect_url': '/customers/discounts'
            })
            
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Error recording discount: {str(e)}'
            })


@login_required
def customer_payment_delete(request, payment_id):
    """Delete a customer payment"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'})
    
    try:
        user_profile = request.user.userprofile
        payment = get_object_or_404(CustomerPayment, id=payment_id, user=user_profile)
        
        # Get associated book log before deleting
        book_log = payment.book_log
        customer = payment.customer
        amount = payment.amount
        
        # Reverse the book entry BEFORE deleting payment
        if book_log:
            book = book_log.parent_book
            # Reverse the payment (subtract from balance since payment reduces debt)
            book.current_balance -= amount
            
            # Update last_log if this was the last entry
            if book.last_log and book.last_log.id == book_log.id:
                # Find previous log
                previous_log = BookLog.objects.filter(
                    parent_book=book
                ).exclude(id=book_log.id).order_by('-date', '-created_at').first()
                book.last_log = previous_log
            
            book.save()
            
            # Manually delete the BookLog
            book_log.delete()
        
        # Now delete payment
        payment.delete()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Payment deleted successfully'
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Error deleting payment: {str(e)}'
        })


@login_required
def customer_discount_delete(request, discount_id):
    """Delete a customer discount"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'})
    
    try:
        user_profile = request.user.userprofile
        discount = get_object_or_404(CustomerDiscount, id=discount_id, user=user_profile)
        
        # Get associated book log before deleting
        book_log = discount.book_log
        customer = discount.customer
        amount = discount.amount
        
        # Reverse the book entry BEFORE deleting discount
        if book_log:
            book = book_log.parent_book
            # Reverse the discount (subtract from balance since discount reduces debt)
            book.current_balance -= amount
            
            # Update last_log if this was the last entry
            if book.last_log and book.last_log.id == book_log.id:
                # Find previous log
                previous_log = BookLog.objects.filter(
                    parent_book=book
                ).exclude(id=book_log.id).order_by('-date', '-created_at').first()
                book.last_log = previous_log
            
            book.save()
            
            # Manually delete the BookLog
            book_log.delete()
        
        # Now delete discount
        discount.delete()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Discount deleted successfully'
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Error deleting discount: {str(e)}'
        })
