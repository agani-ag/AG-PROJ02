# Django imports
from django.contrib import messages
from django.db.models import Max, Sum
from django.http import HttpRequest, JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout, authenticate
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

# Models
from .models import Customer
from .models import Invoice
from .models import Product
from .models import UserProfile
from .models import Inventory
from .models import InventoryLog
from .models import Book
from .models import BookLog
from .models import PurchaseLog

# Utility functions
from .utils import invoice_data_validator
from .utils import invoice_data_processor
from .utils import update_products_from_invoice
from .utils import update_inventory
from .utils import create_inventory
from .utils import add_customer_book
from .utils import auto_deduct_book_from_invoice
from .utils import remove_inventory_entries_for_invoice

# Forms
from .forms import CustomerForm
from .forms import ProductForm
from .forms import UserProfileForm
from .forms import InventoryLogForm
from .forms import BookLogForm

# Third-party libraries
import json
import datetime
import num2words


# ================= Static Pages ==============================
def landing_page(request):
    context = {}
    return render(request, 'gstbillingapp/pages/landing_page.html', context)


# ================= User Management =============================
@login_required
def user_profile_edit(request):
    context = {}
    user_profile = get_object_or_404(UserProfile, user=request.user)
    context['user_profile_form'] = UserProfileForm(instance=user_profile)
    
    if request.method == "POST":
        user_profile_form = UserProfileForm(request.POST, instance=user_profile)
        user_profile_form.save()
        return redirect('user_profile')
    return render(request, 'gstbillingapp/user_profile_edit.html', context)


@login_required
def user_profile(request):
    context = {}
    user_profile = get_object_or_404(UserProfile, user=request.user)
    context['user_profile'] = user_profile
    return render(request, 'gstbillingapp/user_profile.html', context)


def login_view(request):
    if request.user.is_authenticated:
        return redirect("invoice_create")
    context = {}
    auth_form = AuthenticationForm(request)
    if request.method == "POST":
        auth_form = AuthenticationForm(request, data=request.POST)
        if auth_form.is_valid():
            user = auth_form.get_user()
            if user:
                login(request, user)
                return redirect("invoice_create")
        else:
            context["error_message"] = auth_form.get_invalid_login_error()
    context["auth_form"] = auth_form
    return render(request, 'gstbillingapp/login.html', context)


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("invoice_create")
    context = {}
    signup_form = UserCreationForm()
    profile_edit_form = UserProfileForm()
    context["signup_form"] = signup_form
    context["profile_edit_form"] = profile_edit_form

    
    if request.method == "POST":
        signup_form = UserCreationForm(request.POST)
        profile_edit_form = UserProfileForm(request.POST)
        context["signup_form"] = signup_form
        context["profile_edit_form"] = profile_edit_form

        if signup_form.is_valid():
            user = signup_form.save()
        else:
            context["error_message"] = signup_form.errors
            return render(request, 'gstbillingapp/signup.html', context)
        if profile_edit_form.is_valid():
            userprofile = profile_edit_form.save(commit=False)
            userprofile.user = user
            userprofile.save()
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect("invoice_create")

    return render(request, 'gstbillingapp/signup.html', context)

def logout_view(request):
    logout(request)
    return redirect('login_view')


# ================= Invoice, products and customers =============================
@login_required
def invoice_create(request):
    # if business info is blank redirect to update it
    user_profile = get_object_or_404(UserProfile, user=request.user)
    if not user_profile.business_title:
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
            return render(request, 'gstbillingapp/invoice_create.html', context)

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

    return render(request, 'gstbillingapp/invoice_create.html', context)


@login_required
def invoices(request):
    context = {}
    context['invoices'] = Invoice.objects.filter(user=request.user).order_by('-id')
    return render(request, 'gstbillingapp/invoices.html', context)


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
    return render(request, 'gstbillingapp/invoice_printer.html', context)


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


@login_required
def customers(request):
    context = {}
    context['customers'] = Customer.objects.filter(user=request.user)
    return render(request, 'gstbillingapp/customers.html', context)


@login_required
def products(request):
    context = {}
    context['products'] = Product.objects.filter(user=request.user)
    return render(request, 'gstbillingapp/products.html', context)


@login_required
def customersjson(request):
    customers = list(Customer.objects.filter(user=request.user).values())
    return JsonResponse(customers, safe=False)


@login_required
def productsjson(request):
    products = list(Product.objects.filter(user=request.user).values())
    return JsonResponse(products, safe=False)


@login_required
def customer_edit(request, customer_id):
    customer_obj = get_object_or_404(Customer, user=request.user, id=customer_id)
    if request.method == "POST":
        customer_form = CustomerForm(request.POST, instance=customer_obj)
        if customer_form.is_valid():
            new_customer = customer_form.save()
            return redirect('customers')
    context = {}
    context['customer_form'] = CustomerForm(instance=customer_obj)
    return render(request, 'gstbillingapp/customer_edit.html', context)


@login_required
def customer_delete(request):
    if request.method == "POST":
        customer_id = request.POST["customer_id"]
        customer_obj = get_object_or_404(Customer, user=request.user, id=customer_id)
        customer_obj.delete()
    return redirect('customers')


@login_required
def customer_add(request):
    if request.method == "POST":
        customer_form = CustomerForm(request.POST)
        new_customer = customer_form.save(commit=False)
        new_customer.user = request.user
        new_customer.save()
        # create customer book
        add_customer_book(new_customer)
        return redirect('customers')
    context = {}
    context['customer_form'] = CustomerForm()
    return render(request, 'gstbillingapp/customer_edit.html', context)


@login_required
def product_edit(request, product_id):
    product_obj = get_object_or_404(Product, user=request.user, id=product_id)
    if request.method == "POST":
        product_form = ProductForm(request.POST, instance=product_obj)
        if product_form.is_valid():
            new_product = product_form.save()
            return redirect('products')
    context = {}
    context['product_form'] = ProductForm(instance=product_obj)
    return render(request, 'gstbillingapp/product_edit.html', context)


@login_required
def product_add(request):
    if request.method == "POST":
        product_form = ProductForm(request.POST)
        if product_form.is_valid():
            new_product = product_form.save(commit=False)
            new_product.user = request.user
            new_product.save()
            create_inventory(new_product)

            return redirect('products')
    context = {}
    context['product_form'] = ProductForm()
    return render(request, 'gstbillingapp/product_edit.html', context)


@login_required
def product_delete(request):
    if request.method == "POST":
        product_id = request.POST["product_id"]
        product_obj = get_object_or_404(Product, user=request.user, id=product_id)
        product_obj.delete()
    return redirect('products')


# ================= Inventory Views ===========================
@login_required
def inventory(request):
    context = {}
    context['inventory_list'] = Inventory.objects.filter(user=request.user).exclude(product_id__isnull=True)
    context['untracked_products'] = Product.objects.filter(user=request.user, inventory=None).exclude(product_name__isnull=True)
    return render(request, 'gstbillingapp/inventory.html', context)

@login_required
def inventory_logs(request, inventory_id):
    context = {}
    inventory = get_object_or_404(Inventory, id=inventory_id, user=request.user)
    inventory_logs = InventoryLog.objects.filter(user=request.user, product=inventory.product).order_by('-id')
    context['inventory'] = inventory
    context['inventory_logs'] = inventory_logs
    return render(request, 'gstbillingapp/inventory_logs.html', context)


@login_required
def inventory_logs_add(request, inventory_id):
    context = {}
    inventory = get_object_or_404(Inventory, id=inventory_id, user=request.user)
    inventory_logs = Inventory.objects.filter(user=request.user, product=inventory.product)
    context['inventory'] = inventory
    context['inventory_logs'] = inventory_logs
    context['form'] = InventoryLogForm()

    if request.method == "POST":
        inventory_log_form = InventoryLogForm(request.POST)
        invoice_no = request.POST["invoice_no"]
        invoice = None
        if invoice_no:
            try:
                invoice_no = int(invoice_no)
                invoice = Invoice.objects.get(user=request.user, invoice_number=invoice_no)
            except:
                context['error_message'] = "Incorrect invoice number %s"%(invoice_no,)
                return render(request, 'gstbillingapp/inventory_logs_add.html', context)
                context['form'] = inventory_log_form
                return render(request, 'gstbillingapp/inventory_logs_add.html', context)


        inventory_log = inventory_log_form.save(commit=False)
        inventory_log.user = request.user
        inventory_log.product = inventory.product
        if invoice:
            inventory_log.associated_invoice = invoice
        inventory_log.save()
        inventory.current_stock = inventory.current_stock + inventory_log.change
        inventory.last_log = inventory_log
        inventory.save()
        return redirect('inventory_logs', inventory.id)

    
    return render(request, 'gstbillingapp/inventory_logs_add.html', context)

@login_required
def inventory_logs_del(request, inventorylog_id):
    invlg = get_object_or_404(InventoryLog, id=inventorylog_id)
    inv_obj = get_object_or_404(Inventory, id=invlg.product.id, user=request.user)
    invlg.delete()
    new_total = InventoryLog.objects.filter(product=inv_obj.product).aggregate(Sum('change'))['change__sum']
    new_last_log = InventoryLog.objects.filter(product=inv_obj.product).last()
    if not new_total:
        new_total = 0
    inv_obj.current_stock = new_total
    inv_obj.last_log = new_last_log
    inv_obj.save()
    return redirect('inventory_logs', inv_obj.id)


# ===================== Book views =============================
@login_required
def books(request):
    context = {}
    context['book_list'] = Book.objects.filter(user=request.user).exclude(customer_id__isnull=True)
    return render(request, 'gstbillingapp/books.html', context)


@login_required
def book_logs(request, book_id):
    context = {}
    book = get_object_or_404(Book, id=book_id, user=request.user)
    book_logs = BookLog.objects.filter(parent_book=book).order_by('-date')
    context['book'] = book
    context['book_logs'] = book_logs
    return render(request, 'gstbillingapp/book_logs.html', context)


@login_required
def book_logs_add(request, book_id):
    context = {}
    book = get_object_or_404(Book, id=book_id, user=request.user)
    book_logs = BookLog.objects.filter(parent_book=book)
    context['book'] = book
    context['book_logs'] = book_logs
    context['form'] = BookLogForm()

    if request.method == "POST":
        book_log_form = BookLogForm(request.POST)
        invoice_no = request.POST["invoice_no"]
        invoice = None
        if invoice_no:
            try:
                invoice_no = int(invoice_no)
                invoice = Invoice.objects.get(user=request.user, invoice_number=invoice_no)
            except:
                context['error_message'] = "Incorrect invoice number %s"%(invoice_no,)
                return render(request, 'gstbillingapp/book_logs_add.html', context)
                context['form'] = book_log_form
                return render(request, 'gstbillingapp/book_logs_add.html', context)


        book_log = book_log_form.save(commit=False)
        book_log.parent_book = book
        if invoice:
            book_log.associated_invoice = invoice
        book_log.save()

        book.current_balance = book.current_balance + book_log.change
        book.last_log = book_log
        book.save()
        return redirect('book_logs', book.id)

    return render(request, 'gstbillingapp/book_logs_add.html', context)

@login_required
def book_logs_del(request, booklog_id):
    bklg = get_object_or_404(BookLog, id=booklog_id)
    book = get_object_or_404(Book, id=bklg.parent_book.id, user=request.user)
    bklg.delete()
    new_total = BookLog.objects.filter(parent_book=book).aggregate(Sum('change'))['change__sum']
    new_last_log = BookLog.objects.filter(parent_book=book).last()
    if not new_total:
        new_total = 0
    book.current_balance = new_total
    book.last_log = new_last_log
    book.save()
    return redirect('book_logs', book.id)


# ================= Purchases =============================
@login_required
def purchases(request):
    context = {}
    # context['purchases'] = PurchaseLog.objects.filter(user=request.user).order_by('-date')
    context['total_p'] = PurchaseLog.objects.filter(user=request.user, ptype="purchase").aggregate(Sum('amount'))['amount__sum']
    context['total_pp'] = PurchaseLog.objects.filter(user=request.user, ptype="paid").aggregate(Sum('amount'))['amount__sum']
    context['total_pb'] = PurchaseLog.objects.filter(user=request.user).aggregate(Sum('amount'))['amount__sum']

    current_date = datetime.datetime.now().date()
    purchases = PurchaseLog.objects.filter(user=request.user).order_by('date')
    purchases_with_days = []
    temp1,temp2 = 0, 0
    total_paid = context['total_pp'] if context['total_pp'] else 0
    for purchase in purchases:
        days_difference = (current_date - purchase.date.date()).days
        if purchase.ptype == 'purchase':
            total_paid = total_paid + purchase.amount
            if total_paid < 0 and temp2 == 0:
                temp1 = abs(total_paid)
                temp2 = 1
            else:
                temp1 = 'colour2'
            colour = temp1 if total_paid < 0 else 'colour1'
        else:
            colour = 'colour2' if total_paid < 0 else 'colour1'
        purchase_data = purchase.__dict__
        purchase_data['days'] = days_difference
        purchase_data['colour'] = colour
        if purchase_data['days'] > 80 and purchase.ptype == 'purchase':
            if purchase_data['colour'] != 'colour1':
                messages.error(request, f'You Have Pending Purchase Bill of ₹{abs(purchase.amount)} - Ref.No {purchase.addon2}')

        purchases_with_days.append(purchase_data)
    context['purchases'] = purchases_with_days[::-1]
    # context['purchases'] = purchases_with_days
    
    return render(request, 'gstbillingapp/pages/purchases.html', context)

@login_required
def purchases_add(request):
    data = {}
    if request.method == 'POST':
        date = request.POST['date']
        ptype = request.POST['ptype']
        amount = request.POST['amount']
        addon1 = request.POST['addon1']
        addon2 = request.POST['addon2']
        category = request.POST['purchase_category']
        category_other = request.POST['other_category']
        if category == 'Other' and ptype == 'purchase':
            if not category_other:
                messages.error(request, 'Please provide a valid category name.')
                return redirect('purchases_add')
            category_save = category_other
            business_config = get_object_or_404(UserProfile, user=request.user)
            bc = json.loads(business_config.business_config)
            bc['category'].append(category_other)
            business_config.business_config = json.dumps(bc)
            business_config.save()
        else:
            category_save = category
        if ptype == 'purchase':
            if int(amount) > 0 :
                amount = -int(amount)
        else:
            amount = abs(int(amount))
        purchase_log = PurchaseLog(user=request.user, date=date, ptype=ptype,
                category=category_save, amount=amount, addon1=addon1, addon2=addon2)
        purchase_log.save()
        return redirect('purchases')
    
    data['category'] = UserProfile.objects.filter(user=request.user).values('business_config').first()
    if not data['category']['business_config']:
        business_config = get_object_or_404(UserProfile, user=request.user)
        business_config.business_config=json.dumps({'category': []})
        business_config.save()
        data['category'] = []
        return render(request,'gstbillingapp/pages/purchase_add.html',data)
    data['category'] = json.loads(data['category']['business_config']).get('category')
    return render(request,'gstbillingapp/pages/purchase_add.html',data)

@login_required
def purchases_edit(request,pid):
    data = {}
    purchase_log = get_object_or_404(PurchaseLog, user=request.user, id=pid)
    data['plog'] = purchase_log
    if request.method == 'POST':
        pid = int(pid)
        date = request.POST['date']
        ptype = request.POST['ptype']
        amount = request.POST['amount']
        addon1 = request.POST['addon1']
        addon2 = request.POST['addon2']
        category = request.POST['purchase_category']
        category_other = request.POST['other_category']
        print(category, category_other)
        if category == 'Other' and ptype == 'purchase':
            if not category_other:
                messages.error(request, 'Please provide a valid category name.')
                return redirect('purchases_edit', pid=pid)
            category_save = category_other
            business_config = get_object_or_404(UserProfile, user=request.user)
            bc = json.loads(business_config.business_config)
            bc['category'].append(category_other)
            business_config.business_config = json.dumps(bc)
            business_config.save()
        else:
            category_save = category
        if ptype == 'purchase':
            if int(amount) > 0 :
                amount = -int(amount)
        else:
            amount = abs(int(amount))
        purchase_log.date = date
        purchase_log.ptype=ptype
        purchase_log.amount=amount
        purchase_log.addon1=addon1
        purchase_log.addon2=addon2
        purchase_log.category=category_save
        purchase_log.save()
        messages.success(request, 'Your changes have been saved successfully.')
        return redirect('purchases_edit',pid)
    data['category'] = UserProfile.objects.filter(user=request.user).values('business_config').first()
    data['category'] = json.loads(data['category']['business_config']).get('category')
    return render(request,'gstbillingapp/pages/purchase_edit.html',data)

@login_required
def purchases_delete(request,pid):
    if pid:
        purchases_obj = get_object_or_404(PurchaseLog, user=request.user, id=pid)
        purchases_obj.delete()
    return redirect('purchases')