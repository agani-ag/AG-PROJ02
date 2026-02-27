from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Sum, Count, Avg, F, Q, Case, When, FloatField
from django.db.models.functions import ExtractMonth, ExtractYear
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from datetime import date, datetime, timedelta
import json
import calendar

from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404

from ..models import (
    UserProfile, Customer, Invoice, Book, BookLog,
    Product, ProductCategory, Inventory, InventoryLog
)


def sales_report_pdf(request):
    user = request.user
    user_profile = UserProfile.objects.get(user=user)

    customers = Customer.objects.filter(user=user).order_by("customer_name")

    elements = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "Title", parent=styles["Heading1"],
        alignment=1, fontSize=16
    )

    subtitle_style = ParagraphStyle(
        "Sub", parent=styles["Normal"],
        alignment=1, fontSize=10
    )

    # ---------------- RESPONSE ---------------- #
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="sales_report_till_now.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm
    )

    # ---------------- HEADER ---------------- #
    elements.append(Paragraph(user_profile.business_title, title_style))
    elements.append(Paragraph(user_profile.business_address, subtitle_style))
    elements.append(
        Paragraph(
            f"Phone: {user_profile.business_phone} | GST: {user_profile.business_gst}",
            subtitle_style
        )
    )
    elements.append(Spacer(1, 8))
    elements.append(Paragraph("Sales Report (Till Now)", subtitle_style))
    elements.append(Spacer(1, 15))

    # ---------------- TOTALS ---------------- #
    grand_paid = 0.0
    grand_purchased = 0.0
    grand_returned = 0.0
    grand_other = 0.0

    # ---------------- PER CUSTOMER ---------------- #
    for customer in customers:
        book = Book.objects.filter(user=user, customer=customer).first()
        if not book:
            continue

        logs = BookLog.objects.filter(parent_book=book, is_active=True)

        paid = purchased = returned = other = 0.0

        for log in logs:
            if log.change_type == 0:
                paid += log.change
            elif log.change_type == 1:
                purchased += log.change
            elif log.change_type == 2:
                returned += log.change
            elif log.change_type == 3:
                other += log.change

        balance = abs(purchased) - (abs(paid) + abs(returned) + abs(other))

        grand_paid += abs(paid)
        grand_purchased += abs(purchased)
        grand_returned += abs(returned)
        grand_other += abs(other)

        # ---------- CUSTOMER TABLE ---------- #
        customer_table = Table(
            [
                ["Customer", customer.customer_name],
                ["Paid", f"{paid:.2f}"],
                ["Purchased", f"{purchased:.2f}"],
                ["Returned", f"{returned:.2f}"],
                ["Other", f"{other:.2f}"],
                ["Balance", f"{balance:.2f}"],
            ],
            colWidths=[50 * mm, 120 * mm]
        )

        customer_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ]))

        elements.append(customer_table)
        elements.append(Spacer(1, 15))

        # ---------- SIGNATURE (PER CUSTOMER) ---------- #
        sign_table = Table(
            [
                ["Customer Signature", "Authorized Signature"],
                ["", ""],
                ["_______________________", "_______________________"]
            ],
            colWidths=[85 * mm, 85 * mm]
        )

        sign_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 1), (-1, 1), 20),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 20),
            ("GRID", (0, 0), (-1, -1), 0, colors.white),
        ]))

        elements.append(sign_table)
        elements.append(Spacer(1, 25))

    # ---------------- GRAND TOTAL ---------------- #
    grand_balance = abs(grand_purchased) - (abs(grand_paid) + abs(grand_returned) + abs(grand_other))

    total_table = Table(
        [
            ["GRAND TOTAL PAID", f"{grand_paid:.2f}"],
            ["GRAND TOTAL PURCHASED", f"{grand_purchased:.2f}"],
            ["GRAND TOTAL RETURNED", f"{grand_returned:.2f}"],
            ["GRAND TOTAL OTHER", f"{grand_other:.2f}"],
            ["FINAL BALANCE", f"{grand_balance:.2f}"],
        ],
        colWidths=[80 * mm, 90 * mm]
    )

    total_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.lightyellow),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]))

    elements.append(total_table)

    # ---------------- FOOTER ---------------- #
    def page_number(canvas, doc):
        canvas.setFont("Helvetica", 9)
        canvas.drawCentredString(A4[0] / 2, 10 * mm, f"Page {canvas.getPageNumber()}")

    doc.build(elements, onFirstPage=page_number, onLaterPages=page_number)

    return response


@login_required
def bi_dashboard(request):
    """Business Intelligence Dashboard view"""
    user = request.user
    user_profile = UserProfile.objects.filter(user=user).first()
    today = date.today()
    current_month_start = today.replace(day=1)

    # ---- All customers & books ----
    customers = Customer.objects.filter(user=user)
    books = Book.objects.filter(user=user)
    invoices = Invoice.objects.filter(user=user)

    # ---- Financial KPIs ----
    total_revenue = 0.0
    total_outstanding = 0.0
    cash_received_month = 0.0
    pending_amount = 0.0

    for book in books:
        logs = BookLog.objects.filter(parent_book=book, is_active=True)
        purchased = sum(abs(l.change) for l in logs if l.change_type == 1)
        paid = sum(abs(l.change) for l in logs if l.change_type == 0)
        returned = sum(abs(l.change) for l in logs if l.change_type == 2)
        other = sum(abs(l.change) for l in logs if l.change_type == 3)

        total_revenue += purchased
        balance = purchased - (paid + returned + other)
        if balance > 0:
            total_outstanding += balance
            pending_amount += balance

        # Cash received this month
        month_paid = sum(
            abs(l.change) for l in logs
            if l.change_type == 0 and l.date and l.date.date() >= current_month_start
        )
        cash_received_month += month_paid

    # ---- Customer KPIs ----
    total_active_customers = customers.count()
    # Approximate new customers this month (customers who have their first book log this month)
    new_customers = 0
    for book in books:
        first_log = BookLog.objects.filter(parent_book=book, is_active=True).order_by('date').first()
        if first_log and first_log.date and first_log.date.date() >= current_month_start:
            new_customers += 1

    # ---- Per-customer analytics ----
    customer_analytics = []
    for book in books:
        if not book.customer:
            continue
        logs = BookLog.objects.filter(parent_book=book, is_active=True)
        purchased = sum(abs(l.change) for l in logs if l.change_type == 1)
        paid = sum(abs(l.change) for l in logs if l.change_type == 0)
        returned = sum(abs(l.change) for l in logs if l.change_type == 2)
        other = sum(abs(l.change) for l in logs if l.change_type == 3)
        outstanding = purchased - (paid + returned + other)

        total_logs = logs.count()
        purchase_logs = logs.filter(change_type=1)
        return_logs = logs.filter(change_type=2)
        return_count = return_logs.count()
        purchase_count = purchase_logs.count()

        # Avg invoice value
        avg_inv = purchased / purchase_count if purchase_count > 0 else 0

        # Late payment % (logs with change_type=4 Pending / total)
        pending_logs = logs.filter(change_type=4).count()
        late_pct = (pending_logs / total_logs * 100) if total_logs > 0 else 0

        # Return frequency
        return_freq = return_count

        # Risk scoring
        risk_score = 0
        if outstanding > 0:
            risk_score += min(outstanding / 1000, 30)
        risk_score += min(late_pct, 30)
        risk_score += min(return_freq * 5, 20)
        if purchased == 0:
            risk_score += 20

        if risk_score >= 50:
            risk_level = "High"
        elif risk_score >= 25:
            risk_level = "Medium"
        else:
            risk_level = "Low"

        # LTV = total purchased
        ltv = purchased

        customer_analytics.append({
            'name': book.customer.customer_name,
            'total_revenue': round(purchased, 2),
            'outstanding': round(max(outstanding, 0), 2),
            'risk_score': round(risk_score, 1),
            'risk_level': risk_level,
            'ltv': round(ltv, 2),
            'late_payment_pct': round(late_pct, 1),
            'avg_invoice_value': round(avg_inv, 2),
            'return_frequency': return_freq,
        })

    # Sort for top customers by revenue
    top_customers = sorted(customer_analytics, key=lambda x: x['total_revenue'], reverse=True)[:10]

    # High risk customers
    high_risk_customers = [c for c in customer_analytics if c['risk_level'] == 'High']
    high_risk_customers_count = len(high_risk_customers)

    # ---- LTV Section ----
    ltv_values = [c['ltv'] for c in customer_analytics if c['ltv'] > 0]
    avg_ltv = sum(ltv_values) / len(ltv_values) if ltv_values else 0
    highest_ltv_customer = max(customer_analytics, key=lambda x: x['ltv'])['name'] if customer_analytics else 'N/A'
    lowest_ltv_customer = min(customer_analytics, key=lambda x: x['ltv'])['name'] if customer_analytics else 'N/A'

    # ---- Monthly Revenue Trend ----
    monthly_trend = []
    month_data = (
        BookLog.objects.filter(
            parent_book__user=user, is_active=True, change_type=1
        )
        .annotate(month=ExtractMonth('date'), year=ExtractYear('date'))
        .values('year', 'month')
        .annotate(revenue=Sum('change'))
        .order_by('year', 'month')
    )
    for row in month_data:
        month_name = f"{calendar.month_abbr[row['month']]} {row['year']}"
        monthly_trend.append({
            'name': month_name,
            'revenue': abs(round(row['revenue'] or 0, 2)),
        })

    # ---- Sales Forecasting (simple average of last 3 months) ----
    last_3 = monthly_trend[-3:] if len(monthly_trend) >= 3 else monthly_trend
    forecast_revenue = round(sum(m['revenue'] for m in last_3) / len(last_3), 2) if last_3 else 0
    forecast_cashflow = round(forecast_revenue * 0.7, 2)  # Assume ~70% collection rate

    # ---- Transaction KPIs ----
    total_invoices = invoices.count()
    total_invoice_amounts = []
    gst_count = invoices.filter(is_gst=True).count()
    for inv in invoices:
        try:
            inv_data = json.loads(inv.invoice_json)
            grand_total = float(inv_data.get('grand_total', 0))
            total_invoice_amounts.append(grand_total)
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    avg_invoice_value = round(sum(total_invoice_amounts) / len(total_invoice_amounts), 2) if total_invoice_amounts else 0
    gst_percentage = round(gst_count / total_invoices * 100, 1) if total_invoices > 0 else 0

    # Return percentage from book logs
    total_book_logs = BookLog.objects.filter(parent_book__user=user, is_active=True).count()
    return_book_logs = BookLog.objects.filter(parent_book__user=user, is_active=True, change_type=2).count()
    return_percentage = round(return_book_logs / total_book_logs * 100, 1) if total_book_logs > 0 else 0

    context = {
        'user_profile': user_profile,
        # Financial KPIs
        'total_revenue': round(total_revenue, 2),
        'total_outstanding': round(total_outstanding, 2),
        'cash_received_month': round(cash_received_month, 2),
        'pending_amount': round(pending_amount, 2),
        # Customer KPIs
        'total_active_customers': total_active_customers,
        'new_customers': new_customers,
        'high_risk_customers_count': high_risk_customers_count,
        'top_customers': top_customers,
        # Credit Risk
        'high_risk_customers': high_risk_customers,
        # LTV
        'avg_ltv': round(avg_ltv, 2),
        'highest_ltv_customer': highest_ltv_customer,
        'lowest_ltv_customer': lowest_ltv_customer,
        # Sales Forecasting
        'forecast_revenue': forecast_revenue,
        'forecast_cashflow': forecast_cashflow,
        'monthly_trend': monthly_trend,
        # Transaction KPIs
        'total_invoices': total_invoices,
        'avg_invoice_value': avg_invoice_value,
        'return_percentage': return_percentage,
        'gst_percentage': gst_percentage,
    }

    return render(request, 'reports/bi_dashboard.html', context)


@login_required
def inventory_dashboard(request):
    """Product & Inventory Intelligence Dashboard view"""
    user = request.user
    user_profile = UserProfile.objects.filter(user=user).first()

    products = Product.objects.filter(user=user)
    categories = ProductCategory.objects.filter(user=user)
    inventories = Inventory.objects.filter(user=user).select_related('product', 'product__product_category')
    inv_logs = InventoryLog.objects.filter(user=user).select_related('product')

    # ---- 1. Inventory KPIs ----
    total_products = products.count()
    total_stock_value = 0.0
    low_stock_count = 0
    out_of_stock_count = 0
    healthy_stock_count = 0
    warning_stock_count = 0
    critical_stock_count = 0
    total_stock_units = 0

    for inv in inventories:
        rate = inv.product.product_rate_with_gst if inv.product else 0
        total_stock_value += inv.current_stock * rate
        total_stock_units += max(inv.current_stock, 0)

        if inv.current_stock <= 0:
            out_of_stock_count += 1
            critical_stock_count += 1
        elif inv.alert_level > 0 and inv.current_stock <= inv.alert_level:
            low_stock_count += 1
            if inv.current_stock <= inv.alert_level * 0.5:
                critical_stock_count += 1
            else:
                warning_stock_count += 1
        else:
            healthy_stock_count += 1

    # ---- 2. Product Category Analysis ----
    total_categories = categories.count()
    parent_categories = categories.filter(parent_category__isnull=True).count()
    sub_categories = categories.filter(parent_category__isnull=False).count()

    # Category breakdown
    category_breakdown = []
    all_cats = categories.all()
    for cat in all_cats:
        cat_products = products.filter(product_category=cat)
        cat_count = cat_products.count()
        if cat_count == 0:
            continue
        cat_stock = 0
        cat_value = 0.0
        cat_low = 0
        for cp in cat_products:
            inv_item = inventories.filter(product=cp).first()
            if inv_item:
                cat_stock += max(inv_item.current_stock, 0)
                cat_value += inv_item.current_stock * cp.product_rate_with_gst
                if inv_item.current_stock <= 0 or (inv_item.alert_level > 0 and inv_item.current_stock <= inv_item.alert_level):
                    cat_low += 1

        if cat_low > cat_count * 0.5:
            health = "Critical"
        elif cat_low > 0:
            health = "Warning"
        else:
            health = "Healthy"

        category_breakdown.append({
            'name': cat.get_full_path(),
            'product_count': cat_count,
            'total_stock': cat_stock,
            'stock_value': round(cat_value, 2),
            'health': health,
        })
    category_breakdown.sort(key=lambda x: x['stock_value'], reverse=True)

    # ---- 3. Low Stock Products ----
    low_stock_products = []
    for inv in inventories:
        if not inv.product:
            continue
        if inv.current_stock <= 0:
            status = "Out of Stock"
        elif inv.alert_level > 0 and inv.current_stock <= inv.alert_level:
            if inv.current_stock <= inv.alert_level * 0.5:
                status = "Critical"
            else:
                status = "Warning"
        else:
            continue  # healthy, skip

        deficit = inv.alert_level - inv.current_stock if inv.alert_level > 0 else abs(inv.current_stock)
        low_stock_products.append({
            'name': inv.product.model_no,
            'category': inv.product.product_category.get_full_path() if inv.product.product_category else '-',
            'current_stock': inv.current_stock,
            'alert_level': inv.alert_level,
            'deficit': deficit,
            'status': status,
        })
    low_stock_products.sort(key=lambda x: x['current_stock'])

    # ---- 4. Product Performance ----
    # Aggregate from InventoryLog
    # change_type: 0=Other, 1=Purchase, 2=Production, 3=Return, 4=Sales
    product_sales = {}  # product_id -> {sold, returned, purchased, produced, name, category, current_stock}
    for log in inv_logs:
        if not log.product:
            continue
        pid = log.product.id
        if pid not in product_sales:
            inv_item = inventories.filter(product=log.product).first()
            product_sales[pid] = {
                'name': log.product.model_no,
                'category': log.product.product_category.get_full_path() if log.product.product_category else '-',
                'current_stock': inv_item.current_stock if inv_item else 0,
                'sold': 0,
                'returned': 0,
                'purchased': 0,
                'produced': 0,
            }
        change = abs(log.change)
        if log.change_type == 4:  # Sales
            product_sales[pid]['sold'] += change
        elif log.change_type == 3:  # Return
            product_sales[pid]['returned'] += change
        elif log.change_type == 1:  # Purchase
            product_sales[pid]['purchased'] += change
        elif log.change_type == 2:  # Production
            product_sales[pid]['produced'] += change

    # Top selling products
    top_selling_products = sorted(
        [{
            'name': v['name'],
            'category': v['category'],
            'units_sold': v['sold'],
            'units_returned': v['returned'],
            'net_sales': v['sold'] - v['returned'],
            'current_stock': v['current_stock'],
        } for v in product_sales.values()],
        key=lambda x: x['units_sold'],
        reverse=True
    )[:10]

    total_units_sold = sum(v['sold'] for v in product_sales.values())
    total_stock_movements = inv_logs.count()

    # Top selling and most returned product names
    top_selling_product = top_selling_products[0]['name'] if top_selling_products else 'N/A'
    most_returned_list = sorted(product_sales.values(), key=lambda x: x['returned'], reverse=True)
    most_returned_product = most_returned_list[0]['name'] if most_returned_list and most_returned_list[0]['returned'] > 0 else 'N/A'

    # ---- 5. Stock Movement Trends ----
    total_purchased_units = sum(v['purchased'] for v in product_sales.values())
    total_produced_units = sum(v['produced'] for v in product_sales.values())
    total_sold_units = sum(v['sold'] for v in product_sales.values())
    total_returned_units = sum(v['returned'] for v in product_sales.values())

    # Monthly stock movement
    monthly_stock_trend = []
    monthly_data = (
        inv_logs
        .annotate(month=ExtractMonth('date'), year=ExtractYear('date'))
        .values('year', 'month')
        .annotate(
            purchased=Sum(Case(
                When(change_type=1, then=F('change')),
                default=0, output_field=FloatField()
            )),
            produced=Sum(Case(
                When(change_type=2, then=F('change')),
                default=0, output_field=FloatField()
            )),
            sold=Sum(Case(
                When(change_type=4, then=F('change')),
                default=0, output_field=FloatField()
            )),
            returned=Sum(Case(
                When(change_type=3, then=F('change')),
                default=0, output_field=FloatField()
            )),
        )
        .order_by('year', 'month')
    )
    for row in monthly_data:
        if not row['month']:
            continue
        month_name = f"{calendar.month_abbr[row['month']]} {row['year']}"
        purchased = abs(int(row['purchased'] or 0))
        produced = abs(int(row['produced'] or 0))
        sold = abs(int(row['sold'] or 0))
        returned = abs(int(row['returned'] or 0))
        net_change = purchased + produced + returned - sold
        monthly_stock_trend.append({
            'name': month_name,
            'purchased': purchased,
            'produced': produced,
            'sold': sold,
            'returned': returned,
            'net_change': net_change,
        })

    # ---- 6. Product Valuation ----
    products_with_rate = products.filter(product_rate_with_gst__gt=0)
    if products_with_rate.exists():
        highest_val = products_with_rate.order_by('-product_rate_with_gst').first()
        highest_value_product = highest_val.model_no if highest_val else 'N/A'
        highest_value_rate = highest_val.product_rate_with_gst if highest_val else 0
        agg = products_with_rate.aggregate(
            avg_rate=Avg('product_rate_with_gst'),
            avg_gst=Avg('product_gst_percentage'),
            avg_discount=Avg('product_discount'),
        )
        avg_product_rate = round(agg['avg_rate'] or 0, 2)
        avg_gst_percentage = round(agg['avg_gst'] or 0, 1)
        avg_discount = round(agg['avg_discount'] or 0, 1)
    else:
        highest_value_product = 'N/A'
        highest_value_rate = 0
        avg_product_rate = 0
        avg_gst_percentage = 0
        avg_discount = 0

    context = {
        'user_profile': user_profile,
        # Inventory KPIs
        'total_products': total_products,
        'total_stock_value': round(total_stock_value, 2),
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        # Category Analysis
        'total_categories': total_categories,
        'parent_categories': parent_categories,
        'sub_categories': sub_categories,
        'category_breakdown': category_breakdown,
        # Inventory Health
        'healthy_stock_count': healthy_stock_count,
        'warning_stock_count': warning_stock_count,
        'critical_stock_count': critical_stock_count,
        'total_stock_units': total_stock_units,
        'low_stock_products': low_stock_products,
        # Product Performance
        'top_selling_product': top_selling_product,
        'most_returned_product': most_returned_product,
        'total_units_sold': total_units_sold,
        'total_stock_movements': total_stock_movements,
        'top_selling_products': top_selling_products,
        # Stock Movement Trends
        'total_purchased_units': total_purchased_units,
        'total_produced_units': total_produced_units,
        'total_sold_units': total_sold_units,
        'total_returned_units': total_returned_units,
        'monthly_stock_trend': monthly_stock_trend,
        # Product Valuation
        'highest_value_product': highest_value_product,
        'highest_value_rate': highest_value_rate,
        'avg_product_rate': avg_product_rate,
        'avg_gst_percentage': avg_gst_percentage,
        'avg_discount': avg_discount,
    }

    return render(request, 'reports/inventory_dashboard.html', context)


@login_required
def ar_aging_report(request):
    """
    Accounts Receivable (AR) Aging Report
    Outstanding receivables grouped by aging buckets (0-15, 15-30, ... up to 435-450 days)
    Customer-wise exposure with outstanding amounts in each bucket.
    """
    user = request.user
    user_profile = UserProfile.objects.filter(user=user).first()
    today = date.today()

    # Define aging buckets (label, min_days, max_days)
    aging_buckets = []
    step = 15
    for start in range(0, 450, step):
        end = start + step
        aging_buckets.append({
            'label': f'{start}-{end}',
            'min_days': start,
            'max_days': end,
        })

    books = Book.objects.filter(user=user).select_related('customer')

    # Summary KPIs
    total_outstanding = 0.0
    total_overdue = 0.0   # > 30 days
    total_customers_with_outstanding = 0
    total_critical_overdue = 0.0  # > 90 days
    bucket_totals = [0.0] * len(aging_buckets)

    customer_rows = []

    for book in books:
        if not book.customer:
            continue

        logs = BookLog.objects.filter(parent_book=book, is_active=True).order_by('date')

        # Calculate total purchased and total settled
        total_purchased = 0.0
        total_settled = 0.0
        for log in logs:
            if log.change_type == 1:  # Purchased
                total_purchased += abs(log.change)
            elif log.change_type in [0, 2, 3]:  # Paid, Returned, Other
                total_settled += abs(log.change)

        outstanding = total_purchased - total_settled
        if outstanding <= 0.01:
            continue  # No outstanding for this customer

        total_outstanding += outstanding
        total_customers_with_outstanding += 1

        # Distribute outstanding across aging buckets based on invoice dates
        # Collect purchase logs with their ages
        purchase_entries = []
        for log in logs:
            if log.change_type == 1 and log.date:  # Purchased Items
                age_days = (today - log.date.date()).days
                purchase_entries.append({
                    'amount': abs(log.change),
                    'age_days': max(age_days, 0),
                })

        # FIFO: payments settle oldest invoices first
        # Sort oldest first, then apply settlements to oldest purchases
        purchase_entries.sort(key=lambda x: x['age_days'], reverse=True)

        remaining_to_settle = total_settled
        bucket_amounts = [0.0] * len(aging_buckets)

        for entry in purchase_entries:
            if remaining_to_settle >= entry['amount']:
                # This purchase is fully paid off
                remaining_to_settle -= entry['amount']
                continue
            elif remaining_to_settle > 0:
                # Partially paid — only the unpaid portion goes into bucket
                unpaid = entry['amount'] - remaining_to_settle
                remaining_to_settle = 0
            else:
                # Fully unpaid
                unpaid = entry['amount']

            # Place unpaid amount in the correct aging bucket
            for i, bucket in enumerate(aging_buckets):
                if bucket['min_days'] <= entry['age_days'] < bucket['max_days']:
                    bucket_amounts[i] += unpaid
                    break
            else:
                # Beyond 450 days, put in last bucket
                bucket_amounts[-1] += unpaid

        # Update totals
        for i in range(len(aging_buckets)):
            bucket_totals[i] += bucket_amounts[i]

        # Overdue = anything beyond 90 days
        overdue_amount = sum(bucket_amounts[6:])  # from 90-105 onwards
        total_overdue += overdue_amount

        # Critical = beyond 90 days
        critical_amount = sum(bucket_amounts[6:])  # from 90-120 onwards
        total_critical_overdue += critical_amount

        # Determine max age bucket for risk level
        max_bucket_idx = 0
        for i in range(len(bucket_amounts) - 1, -1, -1):
            if bucket_amounts[i] > 0:
                max_bucket_idx = i
                break

        if max_bucket_idx >= 6:  # 90+ days
            risk_level = "High"
        elif max_bucket_idx >= 2:  # 30-89 days
            risk_level = "Medium"
        else:
            risk_level = "Low"

        customer_rows.append({
            'book_id': book.id,
            'name': book.customer.customer_name,
            'phone': book.customer.customer_phone or '-',
            'total_outstanding': round(outstanding, 2),
            'bucket_amounts': [round(b, 2) for b in bucket_amounts],
            'risk_level': risk_level,
            'overdue_amount': round(overdue_amount, 2),
        })

    # Sort by total outstanding descending
    customer_rows.sort(key=lambda x: x['total_outstanding'], reverse=True)

    # Risk distribution
    high_risk_count = sum(1 for c in customer_rows if c['risk_level'] == 'High')
    medium_risk_count = sum(1 for c in customer_rows if c['risk_level'] == 'Medium')
    low_risk_count = sum(1 for c in customer_rows if c['risk_level'] == 'Low')

    context = {
        'user_profile': user_profile,
        'aging_buckets': aging_buckets,
        'customer_rows': customer_rows,
        'bucket_totals': [round(b, 2) for b in bucket_totals],
        'total_outstanding': round(total_outstanding, 2),
        'total_overdue': round(total_overdue, 2),
        'total_critical_overdue': round(total_critical_overdue, 2),
        'total_customers_with_outstanding': total_customers_with_outstanding,
        'high_risk_count': high_risk_count,
        'medium_risk_count': medium_risk_count,
        'low_risk_count': low_risk_count,
        'report_date': today,
    }

    return render(request, 'reports/ar_aging_report.html', context)


@login_required
def credit_aging_report(request):
    """
    Credit Aging Report
    Credit limit utilization, overdue beyond allowed credit period,
    aging buckets 0-15, 15-30, ... up to 435-450 days.
    """
    user = request.user
    user_profile = UserProfile.objects.filter(user=user).first()
    today = date.today()

    # Default credit limit & credit period (change these values as needed)
    DEFAULT_CREDIT_LIMIT = 50000.0
    DEFAULT_CREDIT_PERIOD_DAYS = 90  # Days allowed for payment

    # Aging buckets
    aging_buckets = []
    step = 15
    for start in range(0, 450, step):
        end = start + step
        aging_buckets.append({
            'label': f'{start}-{end}',
            'min_days': start,
            'max_days': end,
        })

    books = Book.objects.filter(user=user).select_related('customer')

    # KPIs
    total_credit_limit = 0.0
    total_utilized = 0.0
    total_overdue_beyond_credit = 0.0
    total_bad_debt_risk = 0.0  # Outstanding > 180 days
    total_customers = 0
    bucket_totals = [0.0] * len(aging_buckets)

    customer_rows = []

    for book in books:
        if not book.customer:
            continue

        logs = BookLog.objects.filter(parent_book=book, is_active=True).order_by('date')

        total_purchased = 0.0
        total_settled = 0.0
        for log in logs:
            if log.change_type == 1:
                total_purchased += abs(log.change)
            elif log.change_type in [0, 2, 3]:
                total_settled += abs(log.change)

        outstanding = total_purchased - total_settled
        if outstanding <= 0.01 and total_purchased <= 0:
            continue

        total_customers += 1
        credit_limit = DEFAULT_CREDIT_LIMIT
        total_credit_limit += credit_limit

        utilized = max(outstanding, 0)
        total_utilized += utilized

        utilization_pct = round((utilized / credit_limit * 100), 1) if credit_limit > 0 else 0

        # Collect purchase entries with age
        purchase_entries = []
        for log in logs:
            if log.change_type == 1 and log.date:
                age_days = (today - log.date.date()).days
                purchase_entries.append({
                    'amount': abs(log.change),
                    'age_days': max(age_days, 0),
                })

        # FIFO: payments settle oldest invoices first
        purchase_entries.sort(key=lambda x: x['age_days'], reverse=True)

        remaining_to_settle = total_settled
        bucket_amounts = [0.0] * len(aging_buckets)
        unpaid_entries = []  # Track entries that still have unpaid amounts

        for entry in purchase_entries:
            if remaining_to_settle >= entry['amount']:
                remaining_to_settle -= entry['amount']
                continue
            elif remaining_to_settle > 0:
                unpaid = entry['amount'] - remaining_to_settle
                remaining_to_settle = 0
            else:
                unpaid = entry['amount']

            unpaid_entries.append({'amount': unpaid, 'age_days': entry['age_days']})

            for i, bucket in enumerate(aging_buckets):
                if bucket['min_days'] <= entry['age_days'] < bucket['max_days']:
                    bucket_amounts[i] += unpaid
                    break
            else:
                bucket_amounts[-1] += unpaid

        for i in range(len(aging_buckets)):
            bucket_totals[i] += bucket_amounts[i]

        # Overdue = outstanding beyond credit period
        overdue_bucket_idx = DEFAULT_CREDIT_PERIOD_DAYS // step
        overdue_beyond_credit = sum(bucket_amounts[overdue_bucket_idx:])
        total_overdue_beyond_credit += overdue_beyond_credit

        # Bad debt risk = outstanding > 2x credit period
        bad_debt_bucket_idx = (DEFAULT_CREDIT_PERIOD_DAYS * 2) // step
        bad_debt_amount = sum(bucket_amounts[bad_debt_bucket_idx:])
        total_bad_debt_risk += bad_debt_amount

        # Find max age of any unpaid outstanding entry
        max_age_days = 0
        for entry in unpaid_entries:
            if entry['age_days'] > max_age_days:
                max_age_days = entry['age_days']

        # Credit status
        if utilization_pct > 100:
            credit_status = "Over Limit"
        elif utilization_pct > 80:
            credit_status = "Near Limit"
        elif utilization_pct > 50:
            credit_status = "Moderate"
        else:
            credit_status = "Healthy"

        # Risk assessment based on aging + utilization
        if bad_debt_amount > 0 or max_age_days > (DEFAULT_CREDIT_PERIOD_DAYS * 2):
            risk_level = "Critical"
        elif overdue_beyond_credit > 0 and utilization_pct > 80:
            risk_level = "High"
        elif overdue_beyond_credit > 0:
            risk_level = "Medium"
        else:
            risk_level = "Low"

        # Payment behavior - avg days to pay
        payment_entries = []
        for log in logs:
            if log.change_type == 0 and log.date:  # Paid
                payment_entries.append(log.date.date())

        avg_payment_days = 0
        if payment_entries and purchase_entries:
            first_purchase = min(e['age_days'] for e in purchase_entries) if purchase_entries else 0
            avg_payment_days = max_age_days // 2 if max_age_days > 0 else 0

        customer_rows.append({
            'book_id': book.id,
            'name': book.customer.customer_name,
            'phone': book.customer.customer_phone or '-',
            'credit_limit': round(credit_limit, 2),
            'total_outstanding': round(max(outstanding, 0), 2),
            'utilization_pct': utilization_pct,
            'credit_status': credit_status,
            'overdue_beyond_credit': round(overdue_beyond_credit, 2),
            'bad_debt_amount': round(bad_debt_amount, 2),
            'max_age_days': max_age_days,
            'avg_payment_days': avg_payment_days,
            'risk_level': risk_level,
            'bucket_amounts': [round(b, 2) for b in bucket_amounts],
        })

    customer_rows.sort(key=lambda x: x['total_outstanding'], reverse=True)

    # Risk counts
    critical_count = sum(1 for c in customer_rows if c['risk_level'] == 'Critical')
    high_risk_count = sum(1 for c in customer_rows if c['risk_level'] == 'High')
    medium_risk_count = sum(1 for c in customer_rows if c['risk_level'] == 'Medium')
    low_risk_count = sum(1 for c in customer_rows if c['risk_level'] == 'Low')

    # Utilization summary
    avg_utilization = round(total_utilized / total_credit_limit * 100, 1) if total_credit_limit > 0 else 0
    over_limit_count = sum(1 for c in customer_rows if c['credit_status'] == 'Over Limit')

    context = {
        'user_profile': user_profile,
        'aging_buckets': aging_buckets,
        'customer_rows': customer_rows,
        'bucket_totals': [round(b, 2) for b in bucket_totals],
        'total_credit_limit': round(total_credit_limit, 2),
        'total_utilized': round(total_utilized, 2),
        'avg_utilization': avg_utilization,
        'total_overdue_beyond_credit': round(total_overdue_beyond_credit, 2),
        'total_bad_debt_risk': round(total_bad_debt_risk, 2),
        'total_customers': total_customers,
        'over_limit_count': over_limit_count,
        'critical_count': critical_count,
        'high_risk_count': high_risk_count,
        'medium_risk_count': medium_risk_count,
        'low_risk_count': low_risk_count,
        'report_date': today,
        'default_credit_limit': DEFAULT_CREDIT_LIMIT,
        'default_credit_period': DEFAULT_CREDIT_PERIOD_DAYS,
    }

    return render(request, 'reports/credit_aging_report.html', context)


# =============================================================================
# Overdue Report (Simple)
# =============================================================================
@login_required
def overdue_report(request):
    """
    Simple Overdue Report — shows customers with outstanding amounts
    older than the selected overdue threshold (days).
    Uses FIFO: payments settle oldest invoices first.
    """
    user = request.user
    user_profile = UserProfile.objects.filter(user=user).first()
    today = date.today()

    # Overdue day options: 15, 30, 45, ... 450
    day_options = list(range(15, 465, 15))

    # Get selected days from query param (default 90)
    selected_days = request.GET.get('days', '90')
    try:
        selected_days = int(selected_days)
        if selected_days not in day_options:
            selected_days = 90
    except (ValueError, TypeError):
        selected_days = 90

    books = Book.objects.filter(user=user).select_related('customer')

    customer_rows = []
    total_overdue = 0.0

    for book in books:
        if not book.customer:
            continue

        logs = BookLog.objects.filter(parent_book=book, is_active=True).order_by('date')

        total_purchased = 0.0
        total_settled = 0.0
        for log in logs:
            if log.change_type == 1:  # Purchased
                total_purchased += abs(log.change)
            elif log.change_type in [0, 2, 3]:  # Paid, Returned, Other
                total_settled += abs(log.change)

        outstanding = total_purchased - total_settled
        if outstanding <= 0.01:
            continue

        # Collect purchase entries with age
        purchase_entries = []
        for log in logs:
            if log.change_type == 1 and log.date:
                age_days = (today - log.date.date()).days
                purchase_entries.append({
                    'amount': abs(log.change),
                    'age_days': max(age_days, 0),
                })

        # FIFO: settle oldest first, find unpaid amounts
        purchase_entries.sort(key=lambda x: x['age_days'], reverse=True)
        remaining_to_settle = total_settled
        overdue_amount = 0.0

        for entry in purchase_entries:
            if remaining_to_settle >= entry['amount']:
                remaining_to_settle -= entry['amount']
                continue
            elif remaining_to_settle > 0:
                unpaid = entry['amount'] - remaining_to_settle
                remaining_to_settle = 0
            else:
                unpaid = entry['amount']

            # Only count if this entry's age exceeds the threshold
            if entry['age_days'] >= selected_days:
                overdue_amount += unpaid

        if overdue_amount <= 0:
            continue

        total_overdue += overdue_amount

        customer_rows.append({
            'book_id': book.id,
            'name': book.customer.customer_name,
            'phone': book.customer.customer_phone or '-',
            'overdue_amount': round(overdue_amount, 2),
        })

    # Sort by overdue amount descending
    customer_rows.sort(key=lambda x: x['overdue_amount'], reverse=True)

    context = {
        'user_profile': user_profile,
        'customer_rows': customer_rows,
        'total_overdue': round(total_overdue, 2),
        'selected_days': selected_days,
        'day_options': day_options,
        'total_customers': len(customer_rows),
        'report_date': today,
    }

    return render(request, 'reports/overdue_report.html', context)


def _escape_md(text):
    """Escape special characters for Telegram MarkdownV2 format."""
    if not text:
        return ''
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    escaped = str(text)
    for ch in special_chars:
        escaped = escaped.replace(ch, f'\\{ch}')
    return escaped


@csrf_exempt
def overdue_report_api(request):
    """
    API endpoint for Overdue Report (multi-user).
    Accepts POST with JSON body: {"user_ids": [1, 2, 3]}
    Or GET with query param: ?user_ids=1,2,3
    Query param: ?days=90 (default 90, options: 15,30,45,...450)
    Returns user-wise grouped overdue data with user details.
    """
    today = date.today()
    day_options = list(range(15, 465, 15))

    # --- Parse user_ids ---
    user_ids = []
    if request.method == 'POST':
        try:
            body = json.loads(request.body.decode('utf-8'))
            user_ids = body.get('user_ids', [])
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON body.'}, status=400)
    else:
        raw = request.GET.get('user_ids', '')
        if raw:
            try:
                user_ids = [int(uid.strip()) for uid in raw.split(',') if uid.strip()]
            except ValueError:
                return JsonResponse({'status': 'error', 'message': 'user_ids must be comma-separated integers.'}, status=400)

    if not user_ids:
        return JsonResponse({'status': 'error', 'message': 'user_ids is required (non-empty array).'}, status=400)

    # --- Parse days ---
    if request.method == 'POST':
        try:
            body = json.loads(request.body.decode('utf-8'))
            selected_days = int(body.get('days', 90))
        except (json.JSONDecodeError, ValueError, TypeError):
            selected_days = 90
    else:
        selected_days = request.GET.get('days', '90')
        try:
            selected_days = int(selected_days)
        except (ValueError, TypeError):
            selected_days = 90

    if selected_days not in day_options:
        selected_days = 90

    # --- Parse markdown flag ---
    include_markdown = False
    if request.method == 'POST':
        try:
            body = json.loads(request.body.decode('utf-8'))
            include_markdown = bool(body.get('markdown', False))
        except (json.JSONDecodeError, ValueError):
            pass
    else:
        md_raw = request.GET.get('markdown', '').lower()
        include_markdown = md_raw in ('true', '1', 'yes')

    # --- Fetch valid users ---
    users = User.objects.filter(pk__in=user_ids)
    found_ids = set(users.values_list('pk', flat=True))
    not_found_ids = [uid for uid in user_ids if uid not in found_ids]

    # --- Build per-user overdue data ---
    results = []
    grand_total_overdue = 0.0
    grand_total_customers = 0
    grand_actual_total_customers = 0

    for user in users:
        # User details
        user_profile = UserProfile.objects.filter(user=user).first()
        user_info = {
            'user_id': user.id,
            'username': user.username,
            'email': user.email or '',
            'business_title': user_profile.business_title or '' if user_profile else '',
            'business_phone': user_profile.business_phone or '' if user_profile else '',
            'business_gst': user_profile.business_gst or '' if user_profile else '',
        }

        # Total customer count for this user
        actual_total_customers = Customer.objects.filter(user=user).count()

        books = Book.objects.filter(user=user).select_related('customer')

        customer_rows = []
        user_total_overdue = 0.0

        for book in books:
            if not book.customer:
                continue

            logs = BookLog.objects.filter(parent_book=book, is_active=True).order_by('date')

            total_purchased = 0.0
            total_settled = 0.0
            for log in logs:
                if log.change_type == 1:
                    total_purchased += abs(log.change)
                elif log.change_type in [0, 2, 3]:
                    total_settled += abs(log.change)

            outstanding = total_purchased - total_settled
            if outstanding <= 0.01:
                continue

            purchase_entries = []
            for log in logs:
                if log.change_type == 1 and log.date:
                    age_days = (today - log.date.date()).days
                    purchase_entries.append({
                        'amount': abs(log.change),
                        'age_days': max(age_days, 0),
                    })

            purchase_entries.sort(key=lambda x: x['age_days'], reverse=True)
            remaining_to_settle = total_settled
            overdue_amount = 0.0

            for entry in purchase_entries:
                if remaining_to_settle >= entry['amount']:
                    remaining_to_settle -= entry['amount']
                    continue
                elif remaining_to_settle > 0:
                    unpaid = entry['amount'] - remaining_to_settle
                    remaining_to_settle = 0
                else:
                    unpaid = entry['amount']

                if entry['age_days'] >= selected_days:
                    overdue_amount += unpaid

            if overdue_amount <= 0:
                continue

            user_total_overdue += overdue_amount

            customer_rows.append({
                'customer_id': book.customer.id,
                'customer_name': book.customer.customer_name,
                'phone': book.customer.customer_phone or '',
                'overdue_amount': round(overdue_amount, 2),
            })

        customer_rows.sort(key=lambda x: x['overdue_amount'], reverse=True)

        grand_total_overdue += user_total_overdue
        grand_total_customers += len(customer_rows)
        grand_actual_total_customers += actual_total_customers

        results.append({
            'user': user_info,
            'actual_total_customers': actual_total_customers,
            'total_overdue': round(user_total_overdue, 2),
            'overdue_customers': len(customer_rows),
            'customers': customer_rows,
        })

    # --- Build Telegram Markdown if requested ---
    markdown_text = None
    if include_markdown:
        lines = []
        lines.append(f'📋 *Overdue Report*')
        lines.append(f'📅 Date: `{today.strftime("%Y-%m-%d")}`')
        lines.append(f'⏳ Overdue Threshold: `{selected_days} days`')
        lines.append('')
        lines.append(f'💰 *Grand Total Overdue:* `₹{grand_total_overdue:,.2f}`')
        lines.append(f'👥 Total Customers: `{grand_actual_total_customers}`')
        lines.append(f'⚠️ Overdue Customers: `{grand_total_customers}`')
        lines.append(f'🏢 Users: `{len(results)}`')
        lines.append('')

        if not_found_ids:
            lines.append(f'❌ Not Found User IDs: `{", ".join(str(i) for i in not_found_ids)}`')
            lines.append('')

        for r in results:
            u = r['user']
            biz_title = u.get('business_title', '') or u.get('username', '')
            lines.append(f'━━━━━━━━━━━━━━━━━━━━━━━━')
            lines.append(f'🏢 *{_escape_md(biz_title)}*')
            if u.get('business_phone'):
                lines.append(f'📞 `{u["business_phone"]}`')
            if u.get('business_gst'):
                lines.append(f'🔖 GST: `{u["business_gst"]}`')
            lines.append(f'👥 Total Customers: `{r["actual_total_customers"]}`')
            lines.append(f'⚠️ Overdue Customers: `{r["overdue_customers"]}`')
            lines.append(f'💰 Total Overdue: `₹{r["total_overdue"]:,.2f}`')
            lines.append('')

            if r['customers']:
                for idx, c in enumerate(r['customers'], 1):
                    cname = _escape_md(c['customer_name'])
                    amt = f'₹{c["overdue_amount"]:,.2f}'
                    lines.append(f'{idx}\\. *{cname}*')
                    lines.append(f'   📞 `{c.get("phone", "") or "-"}`  💰 `{amt}`')
                lines.append('')

        lines.append(f'━━━━━━━━━━━━━━━━━━━━━━━━')
        lines.append(f'📊 *Summary*')
        lines.append(f'Grand Total Overdue: `₹{grand_total_overdue:,.2f}`')
        lines.append(f'Total Customers: `{grand_actual_total_customers}`')
        lines.append(f'Overdue Customers: `{grand_total_customers}`')

        markdown_text = '\n'.join(lines)

    response_data = {
        'status': 'success',
        'report_date': today.strftime('%Y-%m-%d'),
        'selected_days': selected_days,
        'day_options': day_options,
        'grand_total_overdue': round(grand_total_overdue, 2),
        'grand_actual_total_customers': grand_actual_total_customers,
        'grand_overdue_customers': grand_total_customers,
        'users_count': len(results),
        'not_found_user_ids': not_found_ids,
        'results': results,
    }

    if include_markdown:
        return JsonResponse({'status': 'success', 'markdown': markdown_text})

    return JsonResponse(response_data)


# =============================================================================
# Customer Intelligence Analysis
# =============================================================================
@login_required
def customer_analysis(request):
    """
    Comprehensive Customer Intelligence & Analysis Dashboard.
    Uses RFM (Recency, Frequency, Monetary) framework enhanced with
    payment behavior scoring to rank every customer on a 0-100 Health Score.
    """
    import statistics

    user = request.user
    user_profile = UserProfile.objects.filter(user=user).first()
    today = date.today()

    customers = Customer.objects.filter(user=user).order_by('customer_name')
    books = Book.objects.filter(user=user).select_related('customer')
    invoices = Invoice.objects.filter(user=user).select_related('invoice_customer')

    # ---- Build per-customer invoice map ----
    customer_invoices = {}  # customer_id -> list of invoice dicts
    for inv in invoices:
        if not inv.invoice_customer_id:
            continue
        cid = inv.invoice_customer_id
        try:
            inv_data = json.loads(inv.invoice_json)
            amount = float(inv_data.get('invoice_total_amt_with_gst', 0) or inv_data.get('grand_total', 0) or 0)
        except (json.JSONDecodeError, ValueError, TypeError):
            amount = 0
        customer_invoices.setdefault(cid, []).append({
            'date': inv.invoice_date,
            'amount': abs(amount),
        })

    # ---- Analyse each customer ----
    customer_rows = []
    all_monetary = []  # for percentile calc
    all_frequency_rate = []  # invoices per month

    for customer in customers:
        book = books.filter(customer=customer).first()

        # -- Invoice metrics --
        inv_list = customer_invoices.get(customer.id, [])
        inv_list_sorted = sorted(inv_list, key=lambda x: x['date']) if inv_list else []
        invoice_count = len(inv_list_sorted)
        total_invoice_value = sum(i['amount'] for i in inv_list_sorted)

        if inv_list_sorted:
            first_invoice_date = inv_list_sorted[0]['date']
            last_invoice_date = inv_list_sorted[-1]['date']
            days_since_last = (today - last_invoice_date).days
            customer_lifetime_days = max((today - first_invoice_date).days, 1)
            customer_lifetime_months = max(customer_lifetime_days / 30.0, 1)
        else:
            first_invoice_date = None
            last_invoice_date = None
            days_since_last = 9999
            customer_lifetime_days = 0
            customer_lifetime_months = 1

        invoices_per_month = round(invoice_count / customer_lifetime_months, 2) if customer_lifetime_months > 0 else 0

        # avg invoice value
        avg_invoice_value = round(total_invoice_value / invoice_count, 2) if invoice_count > 0 else 0

        # -- Invoice gaps for consistency --
        gaps = []
        for i in range(1, len(inv_list_sorted)):
            gap = (inv_list_sorted[i]['date'] - inv_list_sorted[i - 1]['date']).days
            gaps.append(gap)
        avg_gap = round(statistics.mean(gaps), 1) if gaps else 0
        gap_std = round(statistics.stdev(gaps), 1) if len(gaps) >= 2 else 0

        # -- Frequency pattern --
        if invoice_count <= 1:
            frequency_pattern = 'One-Time'
        elif avg_gap <= 10:
            frequency_pattern = 'Weekly'
        elif avg_gap <= 18:
            frequency_pattern = 'Bi-Weekly'
        elif avg_gap <= 45:
            frequency_pattern = 'Monthly'
        elif avg_gap <= 120:
            frequency_pattern = 'Quarterly'
        else:
            frequency_pattern = 'Sporadic'

        # -- Activity status --
        if invoice_count == 0:
            activity_status = 'No Invoices'
        elif days_since_last <= 30:
            activity_status = 'Active'
        elif days_since_last <= 90:
            activity_status = 'Semi-Active'
        elif days_since_last <= 180:
            activity_status = 'Dormant'
        else:
            activity_status = 'Inactive'

        # -- Invoice trend (last 90 days vs prior 90 days) --
        cutoff_recent = today - timedelta(days=90)
        cutoff_prior = today - timedelta(days=180)
        recent_invoices = [i for i in inv_list_sorted if i['date'] >= cutoff_recent]
        prior_invoices = [i for i in inv_list_sorted if cutoff_prior <= i['date'] < cutoff_recent]
        recent_count = len(recent_invoices)
        prior_count = len(prior_invoices)
        recent_value = sum(i['amount'] for i in recent_invoices)
        prior_value = sum(i['amount'] for i in prior_invoices)

        if recent_count > prior_count:
            invoice_trend = 'Growing'
        elif recent_count == prior_count:
            invoice_trend = 'Stable'
        else:
            invoice_trend = 'Declining'

        if invoice_count <= 1:
            invoice_trend = 'New/One-Time'

        # -- Book / Payment metrics --
        total_purchased = 0
        total_paid = 0
        total_returned = 0
        total_other = 0
        total_pending = 0
        outstanding = 0
        payment_dates = []  # (purchase_date, payment_date) pairs for speed calc

        if book:
            logs = BookLog.objects.filter(parent_book=book, is_active=True).order_by('date')
            for log in logs:
                amt = abs(log.change)
                if log.change_type == 1:
                    total_purchased += amt
                elif log.change_type == 0:
                    total_paid += amt
                    if log.date:
                        payment_dates.append(log.date)
                elif log.change_type == 2:
                    total_returned += amt
                elif log.change_type == 3:
                    total_other += amt
                elif log.change_type == 4:
                    total_pending += amt

            outstanding = total_purchased - (total_paid + total_returned + total_other)
            outstanding = max(outstanding, 0)

        # Payment ratio
        payment_ratio = round((total_paid + total_returned + total_other) / total_purchased * 100, 1) if total_purchased > 0 else 100
        outstanding_ratio = round(outstanding / total_purchased * 100, 1) if total_purchased > 0 else 0

        # -- Payment behavior label --
        if outstanding_ratio <= 5:
            payment_behavior = 'Excellent'
        elif outstanding_ratio <= 15:
            payment_behavior = 'Good'
        elif outstanding_ratio <= 35:
            payment_behavior = 'Fair'
        elif outstanding_ratio <= 60:
            payment_behavior = 'Poor'
        else:
            payment_behavior = 'Critical'

        # =============================================
        # HEALTH SCORE CALCULATION (0 – 100)
        # =============================================

        # 1. Recency Score (0-25)
        if days_since_last <= 7:
            recency_score = 25
        elif days_since_last <= 15:
            recency_score = 22
        elif days_since_last <= 30:
            recency_score = 18
        elif days_since_last <= 60:
            recency_score = 12
        elif days_since_last <= 90:
            recency_score = 6
        elif days_since_last <= 180:
            recency_score = 2
        else:
            recency_score = 0

        # 2. Frequency Score (0-25) — based on invoices/month
        if invoices_per_month >= 4:
            frequency_score = 25
        elif invoices_per_month >= 2:
            frequency_score = 22
        elif invoices_per_month >= 1:
            frequency_score = 18
        elif invoices_per_month >= 0.5:
            frequency_score = 13
        elif invoices_per_month >= 0.25:
            frequency_score = 8
        elif invoice_count >= 1:
            frequency_score = 3
        else:
            frequency_score = 0

        # 3. Monetary Score (0-25) — computed later via percentile
        monetary_raw = total_invoice_value  # placeholder, scored after loop

        # 4. Payment Score (0-25)
        if total_purchased == 0:
            payment_score = 12  # neutral, no data
        else:
            # Base: payment ratio contribution (0-15)
            payment_score = min(round(payment_ratio / 100 * 15), 15)
            # Bonus: low outstanding (0-5)
            if outstanding_ratio <= 5:
                payment_score += 5
            elif outstanding_ratio <= 15:
                payment_score += 3
            elif outstanding_ratio <= 35:
                payment_score += 1
            # Bonus: consistency — low gap std deviation (0-5)
            if gap_std <= 5 and invoice_count >= 3:
                payment_score += 5
            elif gap_std <= 15 and invoice_count >= 3:
                payment_score += 3
            elif gap_std <= 30 and invoice_count >= 2:
                payment_score += 1

        payment_score = min(payment_score, 25)

        all_monetary.append(monetary_raw)
        all_frequency_rate.append(invoices_per_month)

        customer_rows.append({
            'id': customer.id,
            'name': customer.customer_name,
            'phone': customer.customer_phone or '',
            # Invoice metrics
            'invoice_count': invoice_count,
            'total_invoice_value': round(total_invoice_value, 2),
            'avg_invoice_value': avg_invoice_value,
            'first_invoice': first_invoice_date,
            'last_invoice': last_invoice_date,
            'days_since_last': days_since_last if days_since_last != 9999 else None,
            'invoices_per_month': invoices_per_month,
            'avg_gap_days': avg_gap,
            'gap_std': gap_std,
            'frequency_pattern': frequency_pattern,
            'activity_status': activity_status,
            'invoice_trend': invoice_trend,
            'recent_count': recent_count,
            'prior_count': prior_count,
            'recent_value': round(recent_value, 2),
            'prior_value': round(prior_value, 2),
            # Payment metrics
            'total_purchased': round(total_purchased, 2),
            'total_paid': round(total_paid, 2),
            'total_returned': round(total_returned, 2),
            'outstanding': round(outstanding, 2),
            'payment_ratio': payment_ratio,
            'outstanding_ratio': outstanding_ratio,
            'payment_behavior': payment_behavior,
            # Scores
            'recency_score': recency_score,
            'frequency_score': frequency_score,
            'monetary_raw': monetary_raw,
            'payment_score': payment_score,
            # Will be set after percentile calc:
            'monetary_score': 0,
            'health_score': 0,
            'segment': '',
            'rank': 0,
        })

    # ---- Compute Monetary Score via percentile ----
    sorted_monetary = sorted(all_monetary)
    for row in customer_rows:
        if not sorted_monetary or row['monetary_raw'] == 0:
            row['monetary_score'] = 0
        else:
            # percentile rank
            rank_pos = sorted_monetary.index(row['monetary_raw'])
            percentile = rank_pos / len(sorted_monetary) * 100
            if percentile >= 90:
                row['monetary_score'] = 25
            elif percentile >= 75:
                row['monetary_score'] = 21
            elif percentile >= 50:
                row['monetary_score'] = 16
            elif percentile >= 25:
                row['monetary_score'] = 10
            elif row['monetary_raw'] > 0:
                row['monetary_score'] = 4
            else:
                row['monetary_score'] = 0

        # Total Health Score
        row['health_score'] = (
            row['recency_score'] +
            row['frequency_score'] +
            row['monetary_score'] +
            row['payment_score']
        )

        # Segment assignment
        hs = row['health_score']
        if hs >= 80:
            row['segment'] = 'Star'
        elif hs >= 60:
            row['segment'] = 'Loyal'
        elif hs >= 40:
            row['segment'] = 'Promising'
        elif hs >= 20:
            row['segment'] = 'At Risk'
        else:
            row['segment'] = 'Critical'

    # ---- Rank customers by health score desc ----
    customer_rows.sort(key=lambda x: x['health_score'], reverse=True)
    for idx, row in enumerate(customer_rows, 1):
        row['rank'] = idx

    # ---- Summary KPIs ----
    total_customers = len(customer_rows)
    active_count = sum(1 for c in customer_rows if c['activity_status'] == 'Active')
    semi_active_count = sum(1 for c in customer_rows if c['activity_status'] == 'Semi-Active')
    dormant_count = sum(1 for c in customer_rows if c['activity_status'] == 'Dormant')
    inactive_count = sum(1 for c in customer_rows if c['activity_status'] in ('Inactive', 'No Invoices'))
    one_timer_count = sum(1 for c in customer_rows if c['frequency_pattern'] == 'One-Time')

    star_count = sum(1 for c in customer_rows if c['segment'] == 'Star')
    loyal_count = sum(1 for c in customer_rows if c['segment'] == 'Loyal')
    promising_count = sum(1 for c in customer_rows if c['segment'] == 'Promising')
    at_risk_count = sum(1 for c in customer_rows if c['segment'] == 'At Risk')
    critical_count = sum(1 for c in customer_rows if c['segment'] == 'Critical')

    # Frequency pattern counts
    weekly_count = sum(1 for c in customer_rows if c['frequency_pattern'] == 'Weekly')
    biweekly_count = sum(1 for c in customer_rows if c['frequency_pattern'] == 'Bi-Weekly')
    monthly_count = sum(1 for c in customer_rows if c['frequency_pattern'] == 'Monthly')
    quarterly_count = sum(1 for c in customer_rows if c['frequency_pattern'] == 'Quarterly')
    sporadic_count = sum(1 for c in customer_rows if c['frequency_pattern'] == 'Sporadic')

    # Payment behavior counts
    excellent_pmt = sum(1 for c in customer_rows if c['payment_behavior'] == 'Excellent')
    good_pmt = sum(1 for c in customer_rows if c['payment_behavior'] == 'Good')
    fair_pmt = sum(1 for c in customer_rows if c['payment_behavior'] == 'Fair')
    poor_pmt = sum(1 for c in customer_rows if c['payment_behavior'] == 'Poor')
    critical_pmt = sum(1 for c in customer_rows if c['payment_behavior'] == 'Critical')

    # Trend counts
    growing_count = sum(1 for c in customer_rows if c['invoice_trend'] == 'Growing')
    stable_count = sum(1 for c in customer_rows if c['invoice_trend'] == 'Stable')
    declining_count = sum(1 for c in customer_rows if c['invoice_trend'] == 'Declining')

    avg_health = round(statistics.mean([c['health_score'] for c in customer_rows]), 1) if customer_rows else 0
    total_outstanding = sum(c['outstanding'] for c in customer_rows)
    total_revenue = sum(c['total_invoice_value'] for c in customer_rows)

    # Top 10 & Bottom 10
    top_10 = customer_rows[:10]
    bottom_10 = list(reversed(customer_rows[-10:])) if len(customer_rows) >= 10 else list(reversed(customer_rows))

    context = {
        'user_profile': user_profile,
        'report_date': today,
        'customer_rows': customer_rows,
        'total_customers': total_customers,
        # Activity
        'active_count': active_count,
        'semi_active_count': semi_active_count,
        'dormant_count': dormant_count,
        'inactive_count': inactive_count,
        'one_timer_count': one_timer_count,
        # Segments
        'star_count': star_count,
        'loyal_count': loyal_count,
        'promising_count': promising_count,
        'at_risk_count': at_risk_count,
        'critical_count': critical_count,
        # Frequency
        'weekly_count': weekly_count,
        'biweekly_count': biweekly_count,
        'monthly_count': monthly_count,
        'quarterly_count': quarterly_count,
        'sporadic_count': sporadic_count,
        # Payment
        'excellent_pmt': excellent_pmt,
        'good_pmt': good_pmt,
        'fair_pmt': fair_pmt,
        'poor_pmt': poor_pmt,
        'critical_pmt': critical_pmt,
        # Trends
        'growing_count': growing_count,
        'stable_count': stable_count,
        'declining_count': declining_count,
        # Summary
        'avg_health': avg_health,
        'total_outstanding': round(total_outstanding, 2),
        'total_revenue': round(total_revenue, 2),
        # Top / Bottom
        'top_10': top_10,
        'bottom_10': bottom_10,
    }

    return render(request, 'reports/customer_analysis.html', context)
