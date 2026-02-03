from django.http import HttpResponse
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from datetime import date, timedelta
import json
import calendar

from ..models import UserProfile, Customer, Invoice


from django.http import HttpResponse
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle,
    Paragraph, Spacer
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import mm

from ..models import Book, BookLog, Customer, UserProfile


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

