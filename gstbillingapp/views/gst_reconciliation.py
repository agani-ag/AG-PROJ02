# Django imports
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum, Count, Q, Min, Max
from django.http import JsonResponse, HttpResponse

# Models
from ..models import (
    PurchaseInvoice, VendorPurchase, GSTRReconciliation,
    AuditLog, UserProfile, Invoice
)

# Python imports
import json
import csv
from datetime import datetime
from decimal import Decimal


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


# ================= GSTR-2A/2B Reconciliation Views =============================

@login_required
def gstr2_reconciliation(request):
    """Main GSTR-2A/2B reconciliation view"""
    # Get period
    month = request.GET.get('month', datetime.now().month)
    year = request.GET.get('year', datetime.now().year)
    
    try:
        month = int(month)
        year = int(year)
    except (ValueError, TypeError):
        month = datetime.now().month
        year = datetime.now().year
    
    # Get reconciliation records for this period
    reconciliations = GSTRReconciliation.objects.filter(
        user=request.user,
        period_month=month,
        period_year=year
    ).order_by('status', '-created_at')
    
    # Calculate statistics
    stats = {
        'total': reconciliations.count(),
        'matched': reconciliations.filter(status='MATCHED').count(),
        'missing_in_gstr2': reconciliations.filter(status='MISSING_IN_GSTR2').count(),
        'missing_in_books': reconciliations.filter(status='MISSING_IN_BOOKS').count(),
        'amount_mismatch': reconciliations.filter(status='AMOUNT_MISMATCH').count(),
        'date_mismatch': reconciliations.filter(status='DATE_MISMATCH').count(),
        'resolved': reconciliations.filter(resolved=True).count(),
    }
    
    # Get our purchase invoices for this period
    our_invoices = PurchaseInvoice.objects.filter(
        user=request.user,
        invoice_date__month=month,
        invoice_date__year=year
    ).count()
    
    context = {
        'month': month,
        'year': year,
        'period_text': f"{datetime(year, month, 1).strftime('%B %Y')}",
        'reconciliations': reconciliations,
        'stats': stats,
        'our_invoices_count': our_invoices,
        'available_years': get_available_years(request.user),
    }
    
    return render(request, 'gst_reconciliation/gstr2_reconciliation.html', context)


@login_required
def gstr2_upload(request):
    """Upload GSTR-2A/2B CSV for reconciliation"""
    if request.method == 'POST':
        month = int(request.POST.get('month'))
        year = int(request.POST.get('year'))
        
        if 'gstr2_file' not in request.FILES:
            messages.error(request, 'Please select a file to upload')
            return redirect('gstr2_reconciliation')
        
        csv_file = request.FILES['gstr2_file']
        
        if not csv_file.name.endswith('.csv'):
            messages.error(request, 'Please upload a CSV file')
            return redirect('gstr2_reconciliation')
        
        try:
            # Parse CSV
            decoded_file = csv_file.read().decode('utf-8').splitlines()
            reader = csv.DictReader(decoded_file)
            
            processed = 0
            errors = []
            
            for row in reader:
                try:
                    # Extract data from CSV (adjust column names based on actual GSTR-2A format)
                    vendor_gstin = row.get('GSTIN of Supplier', '').strip()
                    invoice_number = row.get('Invoice Number', '').strip()
                    invoice_date_str = row.get('Invoice Date', '').strip()
                    taxable_amount = Decimal(row.get('Taxable Value', 0))
                    cgst = Decimal(row.get('Central Tax', 0))
                    sgst = Decimal(row.get('State/UT Tax', 0))
                    igst = Decimal(row.get('Integrated Tax', 0))
                    
                    # Parse date
                    invoice_date = datetime.strptime(invoice_date_str, '%d-%m-%Y').date()
                    
                    # Check if we have this invoice in our books
                    our_invoice = PurchaseInvoice.objects.filter(
                        user=request.user,
                        vendor__vendor_gst=vendor_gstin,
                        invoice_number=invoice_number
                    ).first()
                    
                    # Determine status
                    if our_invoice:
                        # Check amounts
                        if (abs(float(our_invoice.taxable_amount) - float(taxable_amount)) > 0.01 or
                            abs(float(our_invoice.cgst_amount) - float(cgst)) > 0.01 or
                            abs(float(our_invoice.sgst_amount) - float(sgst)) > 0.01 or
                            abs(float(our_invoice.igst_amount) - float(igst)) > 0.01):
                            status = 'AMOUNT_MISMATCH'
                        elif our_invoice.invoice_date != invoice_date:
                            status = 'DATE_MISMATCH'
                        else:
                            status = 'MATCHED'
                    else:
                        status = 'MISSING_IN_BOOKS'
                    
                    # Create or update reconciliation record
                    reconciliation, created = GSTRReconciliation.objects.update_or_create(
                        user=request.user,
                        period_month=month,
                        period_year=year,
                        vendor_gstin=vendor_gstin,
                        invoice_number=invoice_number,
                        defaults={
                            'purchase_invoice': our_invoice,
                            'vendor_name': row.get('Trade/Legal name of the Supplier', ''),
                            'invoice_date': invoice_date,
                            'our_taxable_amount': our_invoice.taxable_amount if our_invoice else None,
                            'our_cgst': our_invoice.cgst_amount if our_invoice else None,
                            'our_sgst': our_invoice.sgst_amount if our_invoice else None,
                            'our_igst': our_invoice.igst_amount if our_invoice else None,
                            'gstr2_taxable_amount': taxable_amount,
                            'gstr2_cgst': cgst,
                            'gstr2_sgst': sgst,
                            'gstr2_igst': igst,
                            'status': status,
                        }
                    )
                    
                    processed += 1
                    
                except Exception as e:
                    errors.append(f"Row {reader.line_num}: {str(e)}")
            
            # Check for invoices missing in GSTR-2A
            our_invoices = PurchaseInvoice.objects.filter(
                user=request.user,
                invoice_date__month=month,
                invoice_date__year=year
            )
            
            for invoice in our_invoices:
                if invoice.vendor and invoice.vendor.vendor_gst:
                    exists = GSTRReconciliation.objects.filter(
                        user=request.user,
                        period_month=month,
                        period_year=year,
                        vendor_gstin=invoice.vendor.vendor_gst,
                        invoice_number=invoice.invoice_number
                    ).exists()
                    
                    if not exists:
                        GSTRReconciliation.objects.create(
                            user=request.user,
                            period_month=month,
                            period_year=year,
                            purchase_invoice=invoice,
                            vendor_gstin=invoice.vendor.vendor_gst,
                            vendor_name=invoice.vendor.vendor_name,
                            invoice_number=invoice.invoice_number,
                            invoice_date=invoice.invoice_date,
                            our_taxable_amount=invoice.taxable_amount,
                            our_cgst=invoice.cgst_amount,
                            our_sgst=invoice.sgst_amount,
                            our_igst=invoice.igst_amount,
                            status='MISSING_IN_GSTR2',
                        )
            
            if errors:
                messages.warning(request, f'Processed {processed} records with {len(errors)} errors')
                for error in errors[:5]:  # Show first 5 errors
                    messages.error(request, error)
            else:
                messages.success(request, f'Successfully processed {processed} records and completed reconciliation')
            
        except Exception as e:
            messages.error(request, f'Error processing file: {str(e)}')
        
        return redirect('gstr2_reconciliation') + f'?month={month}&year={year}'
    
    # GET request - show upload form
    context = {
        'month': request.GET.get('month', datetime.now().month),
        'year': request.GET.get('year', datetime.now().year),
        'available_years': get_available_years(request.user),
    }
    return render(request, 'gst_reconciliation/gstr2_upload.html', context)


@login_required
def reconciliation_mark_resolved(request, reconciliation_id):
    """Mark a reconciliation issue as resolved"""
    reconciliation = get_object_or_404(GSTRReconciliation, id=reconciliation_id, user=request.user)
    
    if request.method == 'POST':
        action = request.POST.get('action_taken')
        remarks = request.POST.get('remarks')
        
        reconciliation.action_taken = action
        reconciliation.remarks = remarks
        reconciliation.resolved = True
        reconciliation.resolved_date = datetime.now().date()
        reconciliation.save()
        
        messages.success(request, 'Reconciliation marked as resolved')
    
    return redirect('gstr2_reconciliation') + f'?month={reconciliation.period_month}&year={reconciliation.period_year}'


@login_required
def reconciliation_export(request):
    """Export reconciliation report to CSV"""
    month = int(request.GET.get('month', datetime.now().month))
    year = int(request.GET.get('year', datetime.now().year))
    
    reconciliations = GSTRReconciliation.objects.filter(
        user=request.user,
        period_month=month,
        period_year=year
    ).order_by('status', 'vendor_gstin')
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="GSTR2_Reconciliation_{month:02d}_{year}.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'GSTIN', 'Vendor Name', 'Invoice Number', 'Invoice Date', 'Status',
        'Our Taxable Amount', 'GSTR-2 Taxable Amount', 'Difference',
        'Our CGST', 'GSTR-2 CGST', 'Our SGST', 'GSTR-2 SGST',
        'Our IGST', 'GSTR-2 IGST', 'Resolved', 'Action Taken', 'Remarks'
    ])
    
    for rec in reconciliations:
        taxable_diff = (float(rec.our_taxable_amount or 0) - float(rec.gstr2_taxable_amount or 0))
        
        writer.writerow([
            rec.vendor_gstin,
            rec.vendor_name or '',
            rec.invoice_number,
            rec.invoice_date.strftime('%d-%m-%Y'),
            rec.get_status_display(),
            rec.our_taxable_amount or 0,
            rec.gstr2_taxable_amount or 0,
            taxable_diff,
            rec.our_cgst or 0,
            rec.gstr2_cgst or 0,
            rec.our_sgst or 0,
            rec.gstr2_sgst or 0,
            rec.our_igst or 0,
            rec.gstr2_igst or 0,
            'Yes' if rec.resolved else 'No',
            rec.action_taken or '',
            rec.remarks or '',
        ])
    
    return response


# ================= Audit Log Views =============================

@login_required
def audit_log_viewer(request):
    """View audit logs"""
    # Filters
    model_name = request.GET.get('model')
    action = request.GET.get('action')
    days = int(request.GET.get('days', 30))
    
    # Base query
    logs = AuditLog.objects.filter(user=request.user)
    
    # Apply filters
    if model_name:
        logs = logs.filter(model_name=model_name)
    if action:
        logs = logs.filter(action=action)
    
    # Date filter
    from datetime import timedelta
    cutoff_date = datetime.now() - timedelta(days=days)
    logs = logs.filter(timestamp__gte=cutoff_date)
    
    logs = logs.order_by('-timestamp')[:100]  # Limit to 100 records
    
    # Get distinct model names for filter
    model_names = AuditLog.objects.filter(user=request.user).values_list('model_name', flat=True).distinct()
    
    context = {
        'logs': logs,
        'model_names': model_names,
        'selected_model': model_name,
        'selected_action': action,
        'selected_days': days,
    }
    
    return render(request, 'gst_reconciliation/audit_log_viewer.html', context)


@login_required
def audit_log_detail(request, log_id):
    """View detailed audit log"""
    log = get_object_or_404(AuditLog, id=log_id, user=request.user)
    
    # Parse JSON data
    previous_values = json.loads(log.previous_values) if log.previous_values else {}
    new_values = json.loads(log.new_values) if log.new_values else {}
    
    context = {
        'log': log,
        'previous_values': previous_values,
        'new_values': new_values,
    }
    
    return render(request, 'gst_reconciliation/audit_log_detail.html', context)


# ================= Compliance Tracker Views =============================

@login_required
def compliance_tracker(request):
    """Track GST compliance deadlines and status"""
    current_month = datetime.now().month
    current_year = datetime.now().year
    
    # Calculate upcoming deadlines
    from ..utils.gst_calculations import get_gst_filing_due_date
    
    deadlines = []
    
    # GSTR-1
    gstr1_due = get_gst_filing_due_date(current_month, current_year, 'GSTR1')
    days_left_gstr1 = (gstr1_due - datetime.now().date()).days if gstr1_due else None
    deadlines.append({
        'return_type': 'GSTR-1',
        'period': f"{current_month:02d}/{current_year}",
        'month': current_month,
        'year': current_year,
        'due_date': gstr1_due,
        'days_left': days_left_gstr1,
        'days_overdue': abs(days_left_gstr1) if days_left_gstr1 and days_left_gstr1 < 0 else 0,
        'filed': False,
        'url': 'gstr1_report',
    })
    
    # GSTR-3B
    gstr3b_due = get_gst_filing_due_date(current_month, current_year, 'GSTR3B')
    days_left_gstr3b = (gstr3b_due - datetime.now().date()).days if gstr3b_due else None
    deadlines.append({
        'return_type': 'GSTR-3B',
        'period': f"{current_month:02d}/{current_year}",
        'month': current_month,
        'year': current_year,
        'due_date': gstr3b_due,
        'days_left': days_left_gstr3b,
        'days_overdue': abs(days_left_gstr3b) if days_left_gstr3b and days_left_gstr3b < 0 else 0,
        'filed': False,
        'url': 'gstr3b_report',
    })
    
    # Get recent invoices count
    from ..models import Invoice
    recent_invoices = Invoice.objects.filter(
        user=request.user,
        invoice_date__month=current_month,
        invoice_date__year=current_year,
        non_gst_mode=False
    ).count()
    
    recent_purchases = PurchaseInvoice.objects.filter(
        user=request.user,
        invoice_date__month=current_month,
        invoice_date__year=current_year
    ).count()
    
    # Get filed returns
    from ..models import GSTReturn
    filed_returns = GSTReturn.objects.filter(
        user=request.user,
        status='FILED'
    ).order_by('-period_year', '-period_month')[:10]
    
    # Calculate FY
    if current_month >= 4:
        current_fy = f"{current_year}-{str(current_year + 1)[-2:]}"
    else:
        current_fy = f"{current_year - 1}-{str(current_year)[-2:]}"
    
    context = {
        'deadlines': deadlines,
        'upcoming_deadlines': deadlines,  # For template compatibility
        'current_month': current_month,
        'current_year': current_year,
        'current_fy': current_fy,
        'recent_invoices': recent_invoices,
        'recent_purchases': recent_purchases,
        'filed_returns': filed_returns,
    }
    
    return render(request, 'gst_reconciliation/compliance_tracker.html', context)


# ================= Advanced Analytics =============================

@login_required
def gst_analytics(request):
    """Advanced GST analytics and insights"""
    from ..models import Invoice
    
    # Get date range parameters from request
    from_month = request.GET.get('from_month')
    from_year = request.GET.get('from_year')
    to_month = request.GET.get('to_month')
    to_year = request.GET.get('to_year')
    
    # Get current financial year
    current_month = datetime.now().month
    current_year = datetime.now().year
    
    # Set defaults if not provided
    if not from_month or not from_year:
        from_month = 4 if current_month >= 4 else 1
        from_year = current_year if current_month >= 4 else current_year - 1
    else:
        try:
            from_month = int(from_month)
            from_year = int(from_year)
        except (ValueError, TypeError):
            from_month = 4 if current_month >= 4 else 1
            from_year = current_year if current_month >= 4 else current_year - 1
    
    if not to_month or not to_year:
        to_month = current_month
        to_year = current_year
    else:
        try:
            to_month = int(to_month)
            to_year = int(to_year)
        except (ValueError, TypeError):
            to_month = current_month
            to_year = current_year
    
    if current_month >= 4:
        fy_start_year = current_year
        fy_end_year = current_year + 1
    else:
        fy_start_year = current_year - 1
        fy_end_year = current_year
    
    # Monthly trends (last 12 months)
    monthly_data = []
    for i in range(12):
        month = (current_month - i - 1) % 12 + 1
        year = current_year if (current_month - i) > 0 else current_year - 1
        
        sales = Invoice.objects.filter(
            user=request.user,
            invoice_date__month=month,
            invoice_date__year=year,
            non_gst_mode=False
        )
        
        month_total = 0
        month_cgst = 0
        month_sgst = 0
        month_igst = 0
        
        for invoice in sales:
            invoice_json = json.loads(invoice.invoice_json)
            month_total += float(invoice_json['invoice_total_amt_with_gst'])
            month_cgst += float(invoice_json['invoice_total_amt_cgst'])
            month_sgst += float(invoice_json['invoice_total_amt_sgst'])
            month_igst += float(invoice_json['invoice_total_amt_igst'])
        
        monthly_data.insert(0, {
            'month': month,
            'year': year,
            'month_name': datetime(year, month, 1).strftime('%b %Y'),
            'total_sales': month_total,
            'cgst': month_cgst,
            'sgst': month_sgst,
            'igst': month_igst,
            'total_gst': month_cgst + month_sgst + month_igst,
        })
    
    # ITC vs Output Tax comparison
    purchases = PurchaseInvoice.objects.filter(
        user=request.user,
        invoice_date__year=current_year,
        itc_claimed=True
    ).aggregate(
        total_itc=Sum('itc_cgst') + Sum('itc_sgst') + Sum('itc_igst')
    )
    
    # State-wise bifurcation
    state_wise = {}
    for invoice in Invoice.objects.filter(user=request.user, invoice_date__year=current_year, non_gst_mode=False):
        if invoice.invoice_customer and invoice.invoice_customer.customer_gst:
            state_code = invoice.invoice_customer.customer_gst[:2]
            invoice_json = json.loads(invoice.invoice_json)
            total = float(invoice_json['invoice_total_amt_with_gst'])
            
            if state_code not in state_wise:
                state_wise[state_code] = {'count': 0, 'total': 0}
            
            state_wise[state_code]['count'] += 1
            state_wise[state_code]['total'] += total
    
    context = {
        'monthly_data': monthly_data,
        'total_itc': purchases['total_itc'] or 0,
        'state_wise': state_wise,
        'fy_start_year': fy_start_year,
        'fy_end_year': fy_end_year,
        'from_month': from_month,
        'from_year': from_year,
        'to_month': to_month,
        'to_year': to_year,
        'available_years': get_available_years(request.user),
    }
    
    return render(request, 'gst_reconciliation/gst_analytics.html', context)
