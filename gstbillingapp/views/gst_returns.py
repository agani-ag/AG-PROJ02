# Django imports
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum, Count, Q, Min, Max
from django.http import JsonResponse, HttpResponse

# Models
from ..models import (
    Invoice, Customer, UserProfile, GSTReturn,
    PurchaseInvoice, GSTRReconciliation, ReturnInvoice
)
from ..forms import GSTReturnFilterForm

# Python imports
import json
import datetime
from collections import defaultdict


# ================= Utility Functions =============================

def get_available_years(user):
    """Get available years from actual data in database"""
    current_year = datetime.datetime.now().year
    
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


# ================= GSTR-1 Views =============================

@login_required
def gstr1_report(request):
    """Generate GSTR-1 report (Outward Supplies)"""
    # Get period from request
    month = request.GET.get('month', datetime.datetime.now().month)
    year = request.GET.get('year', datetime.datetime.now().year)
    
    try:
        month = int(month)
        year = int(year)
    except (ValueError, TypeError):
        month = datetime.datetime.now().month
        year = datetime.datetime.now().year
    
    # Get all invoices for the period
    invoices = Invoice.objects.filter(
        user=request.user,
        invoice_date__month=month,
        invoice_date__year=year,
        non_gst_mode=False
    ).select_related('invoice_customer')
    
    # B2B - Business to Business (with GSTIN)
    b2b_data = []
    b2b_totals = {
        'taxable_value': 0,
        'cgst': 0,
        'sgst': 0,
        'igst': 0,
        'total': 0,
    }
    
    for invoice in invoices:
        if invoice.invoice_customer and invoice.invoice_customer.customer_gst:
            invoice_json = json.loads(invoice.invoice_json)
            
            entry = {
                'gstin': invoice.invoice_customer.customer_gst,
                'customer_name': invoice.invoice_customer.customer_name,
                'invoice_number': invoice.invoice_number,
                'invoice_date': invoice.invoice_date,
                'invoice_value': invoice_json['invoice_total_amt_with_gst'],
                'taxable_value': invoice_json['invoice_total_amt_without_gst'],
                'cgst': invoice_json['invoice_total_amt_cgst'],
                'sgst': invoice_json['invoice_total_amt_sgst'],
                'igst': invoice_json['invoice_total_amt_igst'],
            }
            
            b2b_data.append(entry)
            b2b_totals['taxable_value'] += float(entry['taxable_value'])
            b2b_totals['cgst'] += float(entry['cgst'])
            b2b_totals['sgst'] += float(entry['sgst'])
            b2b_totals['igst'] += float(entry['igst'])
            b2b_totals['total'] += float(entry['invoice_value'])
    
    # B2C - Business to Consumer (without GSTIN)
    b2c_large = []  # Invoices > 2.5 lakh
    b2c_small_totals = {
        'taxable_value': 0,
        'cgst': 0,
        'sgst': 0,
        'igst': 0,
        'total': 0,
    }
    
    for invoice in invoices:
        if not invoice.invoice_customer or not invoice.invoice_customer.customer_gst:
            invoice_json = json.loads(invoice.invoice_json)
            invoice_value = float(invoice_json['invoice_total_amt_with_gst'])
            
            if invoice_value > 250000:
                # Large invoice - show individually
                b2c_large.append({
                    'customer_name': invoice.invoice_customer.customer_name if invoice.invoice_customer else 'N/A',
                    'invoice_number': invoice.invoice_number,
                    'invoice_date': invoice.invoice_date,
                    'invoice_value': invoice_value,
                    'taxable_value': invoice_json['invoice_total_amt_without_gst'],
                    'cgst': invoice_json['invoice_total_amt_cgst'],
                    'sgst': invoice_json['invoice_total_amt_sgst'],
                    'igst': invoice_json['invoice_total_amt_igst'],
                })
            else:
                # Small invoice - aggregate
                b2c_small_totals['taxable_value'] += float(invoice_json['invoice_total_amt_without_gst'])
                b2c_small_totals['cgst'] += float(invoice_json['invoice_total_amt_cgst'])
                b2c_small_totals['sgst'] += float(invoice_json['invoice_total_amt_sgst'])
                b2c_small_totals['igst'] += float(invoice_json['invoice_total_amt_igst'])
                b2c_small_totals['total'] += invoice_value
    
    # HSN Summary - Group by HSN code
    hsn_summary = defaultdict(lambda: {
        'hsn_code': '',
        'description': '',
        'quantity': 0,
        'taxable_value': 0,
        'cgst': 0,
        'sgst': 0,
        'igst': 0,
        'total_tax': 0,
    })
    
    for invoice in invoices:
        invoice_json = json.loads(invoice.invoice_json)
        for item in invoice_json.get('items', []):
            hsn_code = item.get('invoice_hsn', 'NA')
            
            hsn_summary[hsn_code]['hsn_code'] = hsn_code
            hsn_summary[hsn_code]['description'] = item.get('invoice_product', '')
            hsn_summary[hsn_code]['quantity'] += int(item.get('invoice_qty', 0))
            hsn_summary[hsn_code]['taxable_value'] += float(item.get('invoice_amt_without_gst', 0))
            hsn_summary[hsn_code]['cgst'] += float(item.get('invoice_amt_cgst', 0))
            hsn_summary[hsn_code]['sgst'] += float(item.get('invoice_amt_sgst', 0))
            hsn_summary[hsn_code]['igst'] += float(item.get('invoice_amt_igst', 0))
            hsn_summary[hsn_code]['total_tax'] += (
                float(item.get('invoice_amt_cgst', 0)) +
                float(item.get('invoice_amt_sgst', 0)) +
                float(item.get('invoice_amt_igst', 0))
            )
    
    hsn_summary_list = sorted(hsn_summary.values(), key=lambda x: x['hsn_code'])
    
    # CDNR - Credit/Debit Notes Registered (with GSTIN)
    cdnr_data = []
    cdnr_totals = {
        'taxable_value': 0,
        'cgst': 0,
        'sgst': 0,
        'igst': 0,
        'total': 0,
    }
    
    return_invoices = ReturnInvoice.objects.filter(
        user=request.user.userprofile,
        return_date__month=month,
        return_date__year=year
    ).select_related('customer', 'parent_invoice')
    
    for return_inv in return_invoices:
        if return_inv.customer and return_inv.customer.customer_gst:
            entry = {
                'gstin': return_inv.customer.customer_gst,
                'customer_name': return_inv.customer.customer_name,
                'return_number': return_inv.return_invoice_number,
                'return_date': return_inv.return_date,
                'original_invoice': return_inv.parent_invoice.invoice_number,
                'return_value': return_inv.return_total_amt_with_gst,
                'taxable_value': return_inv.return_total_amt_without_gst,
                'cgst': return_inv.return_total_amt_cgst,
                'sgst': return_inv.return_total_amt_sgst,
                'igst': return_inv.return_total_amt_igst,
            }
            
            cdnr_data.append(entry)
            cdnr_totals['taxable_value'] += float(entry['taxable_value'])
            cdnr_totals['cgst'] += float(entry['cgst'])
            cdnr_totals['sgst'] += float(entry['sgst'])
            cdnr_totals['igst'] += float(entry['igst'])
            cdnr_totals['total'] += float(entry['return_value'])
    
    # CDNUR - Credit/Debit Notes Unregistered (without GSTIN)
    cdnur_data = []
    cdnur_totals = {
        'taxable_value': 0,
        'cgst': 0,
        'sgst': 0,
        'igst': 0,
        'total': 0,
    }
    
    for return_inv in return_invoices:
        if not return_inv.customer or not return_inv.customer.customer_gst:
            entry = {
                'customer_name': return_inv.customer.customer_name if return_inv.customer else 'N/A',
                'return_number': return_inv.return_invoice_number,
                'return_date': return_inv.return_date,
                'original_invoice': return_inv.parent_invoice.invoice_number,
                'return_value': return_inv.return_total_amt_with_gst,
                'taxable_value': return_inv.return_total_amt_without_gst,
                'cgst': return_inv.return_total_amt_cgst,
                'sgst': return_inv.return_total_amt_sgst,
                'igst': return_inv.return_total_amt_igst,
            }
            
            cdnur_data.append(entry)
            cdnur_totals['taxable_value'] += float(entry['taxable_value'])
            cdnur_totals['cgst'] += float(entry['cgst'])
            cdnur_totals['sgst'] += float(entry['sgst'])
            cdnur_totals['igst'] += float(entry['igst'])
            cdnur_totals['total'] += float(entry['return_value'])
    
    # Grand totals (subtract returns from sales)
    grand_totals = {
        'taxable_value': b2b_totals['taxable_value'] + b2c_small_totals['taxable_value'] + sum(x['taxable_value'] for x in b2c_large) - cdnr_totals['taxable_value'] - cdnur_totals['taxable_value'],
        'cgst': b2b_totals['cgst'] + b2c_small_totals['cgst'] + sum(x['cgst'] for x in b2c_large) - cdnr_totals['cgst'] - cdnur_totals['cgst'],
        'sgst': b2b_totals['sgst'] + b2c_small_totals['sgst'] + sum(x['sgst'] for x in b2c_large) - cdnr_totals['sgst'] - cdnur_totals['sgst'],
        'igst': b2b_totals['igst'] + b2c_small_totals['igst'] + sum(x['igst'] for x in b2c_large) - cdnr_totals['igst'] - cdnur_totals['igst'],
        'total': b2b_totals['total'] + b2c_small_totals['total'] + sum(x['invoice_value'] for x in b2c_large) - cdnr_totals['total'] - cdnur_totals['total'],
    }
    
    context = {
        'month': month,
        'year': year,
        'period_text': f"{datetime.date(year, month, 1).strftime('%B %Y')}",
        'b2b_data': b2b_data,
        'b2b_totals': b2b_totals,
        'b2c_large': b2c_large,
        'b2c_small_totals': b2c_small_totals,
        'cdnr_data': cdnr_data,
        'cdnr_totals': cdnr_totals,
        'cdnur_data': cdnur_data,
        'cdnur_totals': cdnur_totals,
        'hsn_summary': hsn_summary_list,
        'grand_totals': grand_totals,
        'invoice_count': invoices.count(),
        'available_years': get_available_years(request.user),
    }
    
    return render(request, 'gst_returns/gstr1_report.html', context)


# ================= GSTR-3B Views =============================

@login_required
def gstr3b_report(request):
    """Generate GSTR-3B report (Summary Return)"""
    # Get period from request
    month = request.GET.get('month', datetime.datetime.now().month)
    year = request.GET.get('year', datetime.datetime.now().year)
    
    try:
        month = int(month)
        year = int(year)
    except (ValueError, TypeError):
        month = datetime.datetime.now().month
        year = datetime.datetime.now().year
    
    # Section 3.1 - Outward Supplies (from sales invoices)
    sales_invoices = Invoice.objects.filter(
        user=request.user,
        invoice_date__month=month,
        invoice_date__year=year,
        non_gst_mode=False
    )
    
    outward_supplies = {
        'taxable_value': 0,
        'cgst': 0,
        'sgst': 0,
        'igst': 0,
        'cess': 0,
    }
    
    for invoice in sales_invoices:
        invoice_json = json.loads(invoice.invoice_json)
        outward_supplies['taxable_value'] += float(invoice_json['invoice_total_amt_without_gst'])
        outward_supplies['cgst'] += float(invoice_json['invoice_total_amt_cgst'])
        outward_supplies['sgst'] += float(invoice_json['invoice_total_amt_sgst'])
        outward_supplies['igst'] += float(invoice_json['invoice_total_amt_igst'])
    
    # Deduct return invoices (credit notes) from outward supplies
    return_invoices = ReturnInvoice.objects.filter(
        user=request.user.userprofile,
        return_date__month=month,
        return_date__year=year
    )
    
    return_totals = return_invoices.aggregate(
        taxable=Sum('return_total_amt_without_gst'),
        cgst=Sum('return_total_amt_cgst'),
        sgst=Sum('return_total_amt_sgst'),
        igst=Sum('return_total_amt_igst')
    )
    
    outward_supplies['taxable_value'] -= float(return_totals['taxable'] or 0)
    outward_supplies['cgst'] -= float(return_totals['cgst'] or 0)
    outward_supplies['sgst'] -= float(return_totals['sgst'] or 0)
    outward_supplies['igst'] -= float(return_totals['igst'] or 0)
    
    # Section 4 - ITC Available (from purchase invoices)
    purchase_invoices = PurchaseInvoice.objects.filter(
        user=request.user,
        invoice_date__month=month,
        invoice_date__year=year,
        itc_claimed=True
    )
    
    itc_available = purchase_invoices.aggregate(
        cgst=Sum('itc_cgst'),
        sgst=Sum('itc_sgst'),
        igst=Sum('itc_igst'),
        cess=Sum('itc_cess'),
    )
    
    # Section 5 - Tax payable
    tax_payable = {
        'cgst': outward_supplies['cgst'] - (itc_available['cgst'] or 0),
        'sgst': outward_supplies['sgst'] - (itc_available['sgst'] or 0),
        'igst': outward_supplies['igst'] - (itc_available['igst'] or 0),
        'cess': outward_supplies['cess'] - (itc_available['cess'] or 0),
    }
    
    # Ensure no negative values
    for key in tax_payable:
        if tax_payable[key] < 0:
            tax_payable[key] = 0
    
    total_tax_payable = tax_payable['cgst'] + tax_payable['sgst'] + tax_payable['igst'] + tax_payable['cess']
    
    context = {
        'month': month,
        'year': year,
        'period_text': f"{datetime.date(year, month, 1).strftime('%B %Y')}",
        'outward_supplies': outward_supplies,
        'itc_available': itc_available,
        'tax_payable': tax_payable,
        'total_tax_payable': total_tax_payable,
        'sales_count': sales_invoices.count(),
        'purchase_count': purchase_invoices.count(),
        'return_count': return_invoices.count(),
        'return_totals': return_totals,
        'available_years': get_available_years(request.user),
    }
    
    return render(request, 'gst_returns/gstr3b_report.html', context)


# ================= GSTR-9 Views =============================

@login_required
def gstr9_report(request):
    """Generate GSTR-9 Annual Return"""
    # Get financial year from 'year' parameter
    fy_year = request.GET.get('year', datetime.datetime.now().year)
    
    try:
        fy_year = int(fy_year)
    except (ValueError, TypeError):
        fy_year = datetime.datetime.now().year
    
    # Financial year: April to March
    start_month = 4
    end_month = 3
    start_year = fy_year
    end_year = fy_year + 1
    
    # Aggregate data for all 12 months
    monthly_data = []
    annual_totals = {
        'taxable_value': 0,
        'cgst': 0,
        'sgst': 0,
        'igst': 0,
        'itc_cgst': 0,
        'itc_sgst': 0,
        'itc_igst': 0,
        'tax_payable': 0,
    }
    
    for month_offset in range(12):
        month = (start_month + month_offset - 1) % 12 + 1
        year = start_year if month >= start_month else end_year
        
        # Sales for this month
        sales = Invoice.objects.filter(
            user=request.user,
            invoice_date__month=month,
            invoice_date__year=year,
            non_gst_mode=False
        )
        
        month_sales = {
            'taxable': 0,
            'cgst': 0,
            'sgst': 0,
            'igst': 0,
        }
        
        for invoice in sales:
            invoice_json = json.loads(invoice.invoice_json)
            month_sales['taxable'] += float(invoice_json['invoice_total_amt_without_gst'])
            month_sales['cgst'] += float(invoice_json['invoice_total_amt_cgst'])
            month_sales['sgst'] += float(invoice_json['invoice_total_amt_sgst'])
            month_sales['igst'] += float(invoice_json['invoice_total_amt_igst'])
        
        # Deduct returns for this month
        returns = ReturnInvoice.objects.filter(
            user=request.user.userprofile,
            return_date__month=month,
            return_date__year=year
        ).aggregate(
            taxable=Sum('return_total_amt_without_gst'),
            cgst=Sum('return_total_amt_cgst'),
            sgst=Sum('return_total_amt_sgst'),
            igst=Sum('return_total_amt_igst')
        )
        
        month_sales['taxable'] -= float(returns['taxable'] or 0)
        month_sales['cgst'] -= float(returns['cgst'] or 0)
        month_sales['sgst'] -= float(returns['sgst'] or 0)
        month_sales['igst'] -= float(returns['igst'] or 0)
        
        # Purchases for this month
        purchases = PurchaseInvoice.objects.filter(
            user=request.user,
            invoice_date__month=month,
            invoice_date__year=year,
            itc_claimed=True
        ).aggregate(
            itc_cgst=Sum('itc_cgst'),
            itc_sgst=Sum('itc_sgst'),
            itc_igst=Sum('itc_igst'),
        )
        
        month_itc = {
            'cgst': purchases['itc_cgst'] or 0,
            'sgst': purchases['itc_sgst'] or 0,
            'igst': purchases['itc_igst'] or 0,
        }
        
        month_tax_payable = (
            month_sales['cgst'] + month_sales['sgst'] + month_sales['igst'] -
            month_itc['cgst'] - month_itc['sgst'] - month_itc['igst']
        )
        
        monthly_data.append({
            'month': month,
            'year': year,
            'month_name': datetime.date(year, month, 1).strftime('%B %Y'),
            'sales': month_sales,
            'itc': month_itc,
            'tax_payable': month_tax_payable,
        })
        
        # Add to annual totals
        annual_totals['taxable_value'] += month_sales['taxable']
        annual_totals['cgst'] += month_sales['cgst']
        annual_totals['sgst'] += month_sales['sgst']
        annual_totals['igst'] += month_sales['igst']
        annual_totals['itc_cgst'] += month_itc['cgst']
        annual_totals['itc_sgst'] += month_itc['sgst']
        annual_totals['itc_igst'] += month_itc['igst']
        annual_totals['tax_payable'] += month_tax_payable
    
    # Get available financial years from data
    available_years_raw = get_available_years(request.user)
    # For GSTR-9, we need financial year (April to March)
    # So a FY starts in April of a year
    available_fy_years = sorted(set([y if m >= 4 else y - 1 for y in available_years_raw for m in [1, 4]]))
    if not available_fy_years:
        available_fy_years = [datetime.datetime.now().year]
    
    context = {
        'fy_year': fy_year,
        'year': fy_year,  # For template compatibility
        'fy_text': f"{fy_year}-{str(fy_year + 1)[-2:]}",
        'financial_year': f"{fy_year}-{str(fy_year + 1)[-2:]}",
        'monthly_data': monthly_data,
        'annual_totals': annual_totals,
        'available_years': available_fy_years,
        'user_profile': request.user.userprofile if hasattr(request.user, 'userprofile') else None,
    }
    
    return render(request, 'gst_returns/gstr9_report.html', context)


# ================= Export Functions =============================

@login_required
def export_gstr1_json(request):
    """Export GSTR-1 in GST portal JSON format"""
    month = request.GET.get('month')
    year = request.GET.get('year')
    
    if not month or not year:
        messages.error(request, "Please specify month and year")
        return redirect('gstr1_report')
    
    # Generate GSTR-1 data (simplified version)
    # In production, this should follow exact GST portal JSON schema
    invoices = Invoice.objects.filter(
        user=request.user,
        invoice_date__month=month,
        invoice_date__year=year,
        non_gst_mode=False
    )
    
    gst_data = {
        'gstin': request.user.userprofile.business_gst,
        'fp': f"{month:02d}{year}",
        'b2b': [],
        'b2cl': [],
        'b2cs': [],
        'cdnr': [],
        'cdnur': [],
    }
    
    # Generate JSON (simplified)
    for invoice in invoices:
        invoice_json = json.loads(invoice.invoice_json)
        if invoice.invoice_customer and invoice.invoice_customer.customer_gst:
            # B2B
            gst_data['b2b'].append({
                'ctin': invoice.invoice_customer.customer_gst,
                'inv': [{
                    'inum': str(invoice.invoice_number),
                    'idt': invoice.invoice_date.strftime('%d-%m-%Y'),
                    'val': float(invoice_json['invoice_total_amt_with_gst']),
                    'itms': [],
                }]
            })
    
    # Add return invoices (CDNR and CDNUR)
    return_invoices = ReturnInvoice.objects.filter(
        user=request.user.userprofile,
        return_date__month=month,
        return_date__year=year
    ).select_related('customer', 'parent_invoice')
    
    for return_inv in return_invoices:
        if return_inv.customer and return_inv.customer.customer_gst:
            # CDNR - Registered
            gst_data['cdnr'].append({
                'ctin': return_inv.customer.customer_gst,
                'nt': [{
                    'ntty': 'C',  # C for Credit Note
                    'nt_num': f"R{return_inv.return_invoice_number}",
                    'nt_dt': return_inv.return_date.strftime('%d-%m-%Y'),
                    'val': float(return_inv.return_total_amt_with_gst),
                    'inv': [{
                        'inum': str(return_inv.parent_invoice.invoice_number),
                        'idt': return_inv.parent_invoice.invoice_date.strftime('%d-%m-%Y')
                    }]
                }]
            })
        else:
            # CDNUR - Unregistered
            gst_data['cdnur'].append({
                'ntty': 'C',
                'nt_num': f"R{return_inv.return_invoice_number}",
                'nt_dt': return_inv.return_date.strftime('%d-%m-%Y'),
                'val': float(return_inv.return_total_amt_with_gst)
            })
    
    # Create response
    response = HttpResponse(json.dumps(gst_data, indent=2), content_type='application/json')
    response['Content-Disposition'] = f'attachment; filename="GSTR1_{month:02d}_{year}.json"'
    
    return response


@login_required
def export_gstr9_json(request):
    """Export GSTR-9 Annual Return in JSON format"""
    year = request.GET.get('year')
    
    if not year:
        messages.error(request, "Please specify financial year")
        return redirect('gstr9_report')
    
    try:
        fy_year = int(year)
    except ValueError:
        messages.error(request, "Invalid year format")
        return redirect('gstr9_report')
    
    # Calculate financial year dates
    fy_start = datetime.date(fy_year, 4, 1)
    fy_end = datetime.date(fy_year + 1, 3, 31)
    financial_year = f"{fy_year}-{str(fy_year + 1)[-2:]}"
    
    # Get annual data
    annual_sales = Invoice.objects.filter(
        user=request.user,
        invoice_date__gte=fy_start,
        invoice_date__lte=fy_end,
        non_gst_mode=False
    )
    
    annual_purchases = PurchaseInvoice.objects.filter(
        user=request.user,
        invoice_date__gte=fy_start,
        invoice_date__lte=fy_end
    )
    
    # Calculate totals
    sales_total = {'taxable': 0, 'cgst': 0, 'sgst': 0, 'igst': 0, 'total': 0}
    for invoice in annual_sales:
        invoice_json = json.loads(invoice.invoice_json)
        sales_total['taxable'] += float(invoice_json['invoice_total_amt_without_gst'])
        sales_total['cgst'] += float(invoice_json['invoice_total_amt_cgst'])
        sales_total['sgst'] += float(invoice_json['invoice_total_amt_sgst'])
        sales_total['igst'] += float(invoice_json['invoice_total_amt_igst'])
        sales_total['total'] += float(invoice_json['invoice_total_amt_with_gst'])
    
    itc_totals = annual_purchases.aggregate(
        itc_cgst=Sum('itc_cgst'),
        itc_sgst=Sum('itc_sgst'),
        itc_igst=Sum('itc_igst')
    )
    
    # Build GSTR-9 JSON structure
    gstr9_data = {
        'gstin': request.user.userprofile.business_gst if hasattr(request.user, 'userprofile') else '',
        'financial_year': financial_year,
        'legal_name': request.user.userprofile.business_name if hasattr(request.user, 'userprofile') else '',
        'trade_name': request.user.userprofile.business_name if hasattr(request.user, 'userprofile') else '',
        'part_ii_outward_supplies': {
            'taxable_value': sales_total['taxable'],
            'central_tax': sales_total['cgst'],
            'state_tax': sales_total['sgst'],
            'integrated_tax': sales_total['igst'],
        },
        'part_iii_itc_claimed': {
            'central_tax': float(itc_totals['itc_cgst'] or 0),
            'state_tax': float(itc_totals['itc_sgst'] or 0),
            'integrated_tax': float(itc_totals['itc_igst'] or 0),
        },
        'part_iv_net_tax_liability': {
            'central_tax': sales_total['cgst'] - float(itc_totals['itc_cgst'] or 0),
            'state_tax': sales_total['sgst'] - float(itc_totals['itc_sgst'] or 0),
            'integrated_tax': sales_total['igst'] - float(itc_totals['itc_igst'] or 0),
        }
    }
    
    # Create response
    response = HttpResponse(json.dumps(gstr9_data, indent=2), content_type='application/json')
    response['Content-Disposition'] = f'attachment; filename="GSTR9_FY{financial_year}.json"'
    
    return response


@login_required
def gst_dashboard(request):
    """GST Analytics Dashboard"""
    # Get month and year from request or default to current
    month = request.GET.get('month', datetime.datetime.now().month)
    year = request.GET.get('year', datetime.datetime.now().year)
    
    try:
        month = int(month)
        year = int(year)
    except (ValueError, TypeError):
        month = datetime.datetime.now().month
        year = datetime.datetime.now().year
    
    # Get sales for selected month
    current_month_sales = Invoice.objects.filter(
        user=request.user,
        invoice_date__month=month,
        invoice_date__year=year,
        non_gst_mode=False
    )
    
    sales_summary = {
        'count': current_month_sales.count(),
        'taxable': 0,
        'cgst': 0,
        'sgst': 0,
        'igst': 0,
        'total': 0,
    }
    
    for invoice in current_month_sales:
        invoice_json = json.loads(invoice.invoice_json)
        sales_summary['taxable'] += float(invoice_json['invoice_total_amt_without_gst'])
        sales_summary['cgst'] += float(invoice_json['invoice_total_amt_cgst'])
        sales_summary['sgst'] += float(invoice_json['invoice_total_amt_sgst'])
        sales_summary['igst'] += float(invoice_json['invoice_total_amt_igst'])
        sales_summary['total'] += float(invoice_json['invoice_total_amt_with_gst'])
    
    # ITC summary
    current_month_purchases = PurchaseInvoice.objects.filter(
        user=request.user,
        invoice_date__month=month,
        invoice_date__year=year,
        itc_claimed=True
    ).aggregate(
        itc_cgst=Sum('itc_cgst'),
        itc_sgst=Sum('itc_sgst'),
        itc_igst=Sum('itc_igst'),
    )
    
    total_itc = (
        (current_month_purchases['itc_cgst'] or 0) +
        (current_month_purchases['itc_sgst'] or 0) +
        (current_month_purchases['itc_igst'] or 0)
    )
    
    # Tax liability
    total_output_tax = sales_summary['cgst'] + sales_summary['sgst'] + sales_summary['igst']
    net_tax_payable = total_output_tax - total_itc
    
    context = {
        'month': month,
        'year': year,
        'current_month': month,
        'current_year': year,
        'period_text': f"{datetime.date(year, month, 1).strftime('%B %Y')}",
        'sales_summary': sales_summary,
        'itc_summary': current_month_purchases,
        'total_itc': total_itc,
        'total_output_tax': total_output_tax,
        'net_tax_payable': net_tax_payable,
        'available_years': get_available_years(request.user),
    }
    
    return render(request, 'gst_returns/gst_dashboard.html', context)
