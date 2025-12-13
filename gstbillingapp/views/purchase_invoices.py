# Django imports
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum, Q, Min, Max
from django.http import JsonResponse

# Models
from ..models import PurchaseInvoice, VendorPurchase, UserProfile, AuditLog, PurchaseLog, Invoice
from ..forms import PurchaseInvoiceForm

# Python imports
import json
from datetime import datetime


# ================= Utility Functions =============================

def get_available_years(user):
    """Get available years from actual data in database"""
    current_year = datetime.now().year
    
    # Get year range from invoices
    invoice_years = Invoice.objects.filter(user=user).aggregate(
        min_year=Min('invoice_date__year'),
        max_year=Max('invoice_date__year')
    )
    
    # Get year range from purchase invoices
    purchase_years = PurchaseInvoice.objects.filter(user=user).aggregate(
        min_year=Min('invoice_date__year'),
        max_year=Max('invoice_date__year')
    )
    
    # Determine the full range
    min_year = min(
        invoice_years['min_year'] or current_year,
        purchase_years['min_year'] or current_year
    )
    max_year = max(
        invoice_years['max_year'] or current_year,
        purchase_years['max_year'] or current_year,
        current_year  # Always include current year
    )
    
    # Add next year for planning
    max_year = max(max_year, current_year + 1)
    
    # Generate year list
    years = list(range(min_year, max_year + 1))
    return years


# ================= Purchase Invoice Views =============================

@login_required
def purchase_invoice_list(request):
    """List all purchase invoices"""
    # Get filter parameters
    month = request.GET.get('month')
    year = request.GET.get('year')
    vendor_id = request.GET.get('vendor')
    
    # Base query with related objects
    invoices = PurchaseInvoice.objects.filter(user=request.user).select_related('vendor', 'related_purchase_log')
    
    # Apply filters
    if month and year:
        invoices = invoices.filter(invoice_date__month=month, invoice_date__year=year)
    elif year:
        invoices = invoices.filter(invoice_date__year=year)
    
    if vendor_id:
        invoices = invoices.filter(vendor_id=vendor_id)
    
    # Calculate totals
    totals = invoices.aggregate(
        total_taxable=Sum('taxable_amount'),
        total_cgst=Sum('cgst_amount'),
        total_sgst=Sum('sgst_amount'),
        total_igst=Sum('igst_amount'),
        total_amount=Sum('total_amount'),
        total_itc=Sum('itc_cgst') + Sum('itc_sgst') + Sum('itc_igst')
    )
    
    # Get vendors for filter dropdown
    vendors = VendorPurchase.objects.filter(user=request.user)
    
    # Get recent purchase logs for linking
    purchase_logs = PurchaseLog.objects.filter(user=request.user, ptype=0).order_by('-date')[:50]
    
    context = {
        'invoices': invoices,
        'totals': totals,
        'vendors': vendors,
        'selected_month': month,
        'selected_year': year,
        'selected_vendor': vendor_id,
        'purchase_logs': purchase_logs,
        'available_years': get_available_years(request.user),
    }
    
    return render(request, 'purchase_invoices/purchase_invoice_list.html', context)


@login_required
def purchase_invoice_add(request):
    """Add new purchase invoice"""
    # Check if linked from purchase log
    purchase_log_id = request.GET.get('purchase_log_id')
    initial_data = {}
    
    if purchase_log_id:
        try:
            purchase_log = PurchaseLog.objects.get(id=purchase_log_id, user=request.user)
            initial_data = {
                'vendor': purchase_log.vendor,
                'invoice_date': purchase_log.date.date() if purchase_log.date else None,
                'total_amount': abs(purchase_log.amount) if purchase_log.amount else 0,
            }
        except PurchaseLog.DoesNotExist:
            pass
    
    if request.method == 'POST':
        form = PurchaseInvoiceForm(request.POST, user=request.user)
        if form.is_valid():
            purchase_invoice = form.save(commit=False)
            purchase_invoice.user = request.user
            
            # Link to purchase log if provided
            log_id = request.POST.get('related_purchase_log')
            if log_id:
                try:
                    purchase_invoice.related_purchase_log = PurchaseLog.objects.get(id=log_id, user=request.user)
                except PurchaseLog.DoesNotExist:
                    pass
            
            purchase_invoice.save()
            
            # Create audit log
            create_audit_log(request, 'CREATE', 'PurchaseInvoice', purchase_invoice.id, 
                           str(purchase_invoice))
            
            messages.success(request, f'Purchase invoice {purchase_invoice.invoice_number} added successfully!')
            return redirect('purchase_invoice_list')
    else:
        form = PurchaseInvoiceForm(user=request.user, initial=initial_data)
    
    # Get recent purchase logs for dropdown
    purchase_logs = PurchaseLog.objects.filter(user=request.user, ptype=0).order_by('-date')[:50]
    
    context = {
        'form': form,
        'title': 'Add Purchase Invoice',
        'purchase_logs': purchase_logs,
        'selected_purchase_log': purchase_log_id,
    }
    
    return render(request, 'purchase_invoices/purchase_invoice_form.html', context)


@login_required
def purchase_invoice_edit(request, pk):
    """Edit existing purchase invoice"""
    purchase_invoice = get_object_or_404(PurchaseInvoice, pk=pk, user=request.user)
    
    if request.method == 'POST':
        form = PurchaseInvoiceForm(request.POST, instance=purchase_invoice, user=request.user)
        if form.is_valid():
            # Store old values for audit
            old_values = {
                'invoice_number': purchase_invoice.invoice_number,
                'total_amount': str(purchase_invoice.total_amount),
                'itc_claimed': purchase_invoice.itc_claimed,
            }
            
            updated_invoice = form.save()
            
            # Create audit log
            new_values = {
                'invoice_number': updated_invoice.invoice_number,
                'total_amount': str(updated_invoice.total_amount),
                'itc_claimed': updated_invoice.itc_claimed,
            }
            
            create_audit_log(request, 'UPDATE', 'PurchaseInvoice', updated_invoice.id,
                           str(updated_invoice), old_values, new_values)
            
            messages.success(request, f'Purchase invoice {updated_invoice.invoice_number} updated successfully!')
            return redirect('purchase_invoice_list')
    else:
        form = PurchaseInvoiceForm(instance=purchase_invoice, user=request.user)
    
    context = {
        'form': form,
        'title': 'Edit Purchase Invoice',
        'invoice': purchase_invoice,
    }
    
    return render(request, 'purchase_invoices/purchase_invoice_form.html', context)


@login_required
def purchase_invoice_view(request, pk):
    """View purchase invoice details"""
    invoice = get_object_or_404(PurchaseInvoice, pk=pk, user=request.user)
    
    context = {
        'invoice': invoice,
    }
    
    return render(request, 'purchase_invoices/purchase_invoice_view.html', context)


@login_required
def purchase_invoice_delete(request, pk):
    """Delete purchase invoice"""
    invoice = get_object_or_404(PurchaseInvoice, pk=pk, user=request.user)
    
    if request.method == 'POST':
        invoice_number = invoice.invoice_number
        
        # Create audit log before deletion
        create_audit_log(request, 'DELETE', 'PurchaseInvoice', invoice.id, str(invoice))
        
        invoice.delete()
        
        messages.success(request, f'Purchase invoice {invoice_number} deleted successfully!')
        return redirect('purchase_invoice_list')
    
    context = {
        'invoice': invoice,
    }
    
    return render(request, 'purchase_invoices/purchase_invoice_confirm_delete.html', context)


@login_required
def purchase_invoice_api_add(request):
    """API endpoint to add purchase invoice (JSON)"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            # Get vendor
            vendor = None
            if data.get('vendor_id'):
                vendor = VendorPurchase.objects.get(id=data['vendor_id'], user=request.user)
            
            # Create invoice
            invoice = PurchaseInvoice(
                user=request.user,
                vendor=vendor,
                invoice_number=data['invoice_number'],
                invoice_date=data['invoice_date'],
                place_of_supply=data.get('place_of_supply', ''),
                taxable_amount=data['taxable_amount'],
                cgst_amount=data.get('cgst_amount', 0),
                sgst_amount=data.get('sgst_amount', 0),
                igst_amount=data.get('igst_amount', 0),
                cess_amount=data.get('cess_amount', 0),
                total_amount=data['total_amount'],
                itc_claimed=data.get('itc_claimed', True),
                notes=data.get('notes', ''),
            )
            invoice.save()
            
            return JsonResponse({
                'status': 'success',
                'message': 'Purchase invoice added successfully',
                'invoice_id': invoice.id,
            })
            
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e),
            }, status=400)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)


@login_required
def itc_ledger(request):
    """View ITC ledger"""
    # Get filter parameters
    month = request.GET.get('month')
    year = request.GET.get('year')
    
    # Base query for ITC claimed invoices
    invoices = PurchaseInvoice.objects.filter(user=request.user, itc_claimed=True)
    
    # Apply filters
    if month and year:
        invoices = invoices.filter(invoice_date__month=month, invoice_date__year=year)
    elif year:
        invoices = invoices.filter(invoice_date__year=year)
    
    # Calculate ITC summary
    itc_summary = invoices.aggregate(
        total_itc_cgst=Sum('itc_cgst'),
        total_itc_sgst=Sum('itc_sgst'),
        total_itc_igst=Sum('itc_igst'),
        total_itc_cess=Sum('itc_cess'),
    )
    
    # Calculate total ITC
    total_itc = (
        (itc_summary['total_itc_cgst'] or 0) +
        (itc_summary['total_itc_sgst'] or 0) +
        (itc_summary['total_itc_igst'] or 0) +
        (itc_summary['total_itc_cess'] or 0)
    )
    
    context = {
        'invoices': invoices,
        'itc_summary': itc_summary,
        'total_itc': total_itc,
        'month': month,
        'year': year,
        'selected_month': month,
        'selected_year': year,
        'available_years': get_available_years(request.user),
    }
    
    return render(request, 'purchase_invoices/itc_ledger.html', context)


# ================= Helper Functions =============================

def create_audit_log(request, action, model_name, object_id, object_repr, 
                     old_values=None, new_values=None):
    """Create audit log entry"""
    try:
        # Get IP address
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        
        # Create audit log
        audit_log = AuditLog(
            user=request.user,
            action=action,
            model_name=model_name,
            object_id=object_id,
            object_repr=object_repr,
            ip_address=ip,
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
        )
        
        if old_values:
            audit_log.previous_values = json.dumps(old_values)
        if new_values:
            audit_log.new_values = json.dumps(new_values)
        
        audit_log.save()
    except Exception as e:
        # Don't fail if audit log creation fails
        print(f"Audit log error: {e}")
