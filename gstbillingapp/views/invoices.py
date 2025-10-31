# Django imports
from django.contrib import messages
from django.db.models import Max, Sum
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

# Models
from ..models import Customer
from ..models import Invoice
from ..models import UserProfile
from ..models import Book
from ..models import BookLog

# Utility functions
from ..utils import invoice_data_validator
from ..utils import invoice_data_processor
from ..utils import update_products_from_invoice
from ..utils import update_inventory
from ..utils import add_customer_book
from ..utils import auto_deduct_book_from_invoice
from ..utils import remove_inventory_entries_for_invoice

# Third-party libraries
import json
import datetime
import num2words


# ================= Invoice, products and customers =============================
@login_required
def invoice_create(request):
    # if business info is blank redirect to update it
    user_profile = get_object_or_404(UserProfile, user=request.user)
    if not user_profile.business_title:
        return redirect('user_profile_edit')
    if not user_profile.business_gst:
        messages.warning(request, "Please update your business GST number before creating invoices.")
        return redirect('user_profile_edit')

    context = {}
    context['default_invoice_number'] = Invoice.objects.filter(user=request.user).aggregate(Max('invoice_number'))['invoice_number__max']
    if not context['default_invoice_number']:
        context['default_invoice_number'] = 1
    else:
        context['default_invoice_number'] += 1

    context['default_invoice_date'] = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d')

    if request.method == 'POST':
        print("POST received - Invoice Data")

        invoice_data = request.POST

        validation_error = invoice_data_validator(invoice_data)
        if validation_error:
            context["error_message"] = validation_error
            return render(request, 'invoices/invoice_create.html', context)

        # valid invoice data
        print("Valid Invoice Data")

        invoice_data_processed = invoice_data_processor(invoice_data)
        # save customer
        customer = None

        try:
            customer = Customer.objects.get(user=request.user,
                                            customer_name=invoice_data['customer-name'],
                                            customer_address=invoice_data['customer-address'],
                                            customer_phone=invoice_data['customer-phone'],
                                            customer_gst=invoice_data['customer-gst'])
        except:
            print("===============> customer not found")
            print(invoice_data['customer-name'])
            print(invoice_data['customer-address'])
            print(invoice_data['customer-phone'])
            print(invoice_data['customer-gst'])

        if not customer:
            print("CREATING CUSTOMER===============>")
            customer = Customer(user=request.user,
                customer_name=invoice_data['customer-name'],
                customer_address=invoice_data['customer-address'],
                customer_phone=invoice_data['customer-phone'],
                customer_gst=invoice_data['customer-gst'])
            # create customer book
            customer.save()
            add_customer_book(customer)

        # save product
        update_products_from_invoice(invoice_data_processed, request)


        # save invoice
        invoice_data_processed_json = json.dumps(invoice_data_processed)
        new_invoice = Invoice(user=request.user,
                              invoice_number=int(invoice_data['invoice-number']),
                              invoice_date=datetime.datetime.strptime(invoice_data['invoice-date'], '%Y-%m-%d'),
                              invoice_customer=customer, invoice_json=invoice_data_processed_json)
        new_invoice.save()
        print("INVOICE SAVED")

        update_inventory(new_invoice, request)
        print("INVENTORY UPDATED")

        auto_deduct_book_from_invoice(new_invoice)
        print("CUSTOMER BOOK UPDATED")


        return redirect('invoice_viewer', invoice_id=new_invoice.id)

    return render(request, 'invoices/invoice_create.html', context)


@login_required
def invoices(request):
    context = {}
    context['invoices'] = Invoice.objects.filter(user=request.user).order_by('-id')
    return render(request, 'invoices/invoices.html', context)


@login_required
def invoice_viewer(request, invoice_id):
    invoice_obj = get_object_or_404(Invoice, user=request.user, id=invoice_id)
    user_profile = get_object_or_404(UserProfile, user=request.user)

    context = {}
    context['invoice'] = invoice_obj
    context['invoice_data'] = json.loads(invoice_obj.invoice_json)
    print(context['invoice_data'])
    context['currency'] = "₹"
    context['total_in_words'] = num2words.num2words(int(context['invoice_data']['invoice_total_amt_with_gst']), lang='en_IN').title()
    context['user_profile'] = user_profile
    return render(request, 'invoices/invoice_printer.html', context)


@login_required
def invoice_delete(request):
    if request.method == "POST":
        invoice_id = request.POST["invoice_id"]
        invoice_obj = get_object_or_404(Invoice, user=request.user, id=invoice_id)
        if len(request.POST.getlist('inventory-del')):
            remove_inventory_entries_for_invoice(invoice_obj, request.user)
        if len(request.POST.getlist('book-del')):
            booklog_obj = get_object_or_404(BookLog,associated_invoice=invoice_obj)
            book = get_object_or_404(Book,user=request.user,id=booklog_obj.parent_book.id)
            booklog_obj.delete()
            new_total = BookLog.objects.filter(parent_book=book).aggregate(Sum('change'))['change__sum']
            new_last_log = BookLog.objects.filter(parent_book=book).last()
            if not new_total:
                new_total = 0
            book.current_balance = new_total
            book.last_log = new_last_log
            book.save()
        invoice_obj.delete()
    return redirect('invoices')