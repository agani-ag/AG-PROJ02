from django.http import HttpResponse
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
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

