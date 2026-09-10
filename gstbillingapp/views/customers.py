# Django imports
import csv
from gstbilling import settings
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
# Models
from ..models import Book, Customer, UserProfile

# Utility functions
from ..utils import add_customer_book
from ..parties import app_enabled, party_for, refresh_for_customer, refresh_login

# Forms
from ..forms import CustomerForm

# Python imports
import json
from ..utils import _escape_md


# ================= Customer Views ===========================
def _filtered_customers(request):
    qs = Customer.objects.filter(user=request.user).order_by('customer_name')
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(customer_name__icontains=q) | Q(customer_phone__icontains=q) | Q(customer_gst__icontains=q))
    return qs, q


@login_required
def customers(request):
    qs, q = _filtered_customers(request)
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'customers/customers.html', {
        'customers': page_obj, 'page_obj': page_obj, 'total_count': paginator.count,
        'q': q, 'querystring': params.urlencode(),
        'customer_app_enabled': app_enabled(request.user),
    })


@login_required
def customers_export(request):
    qs, _q = _filtered_customers(request)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="customers.csv"'
    writer = csv.writer(response)
    writer.writerow(['Customer Name', 'Address', 'Phone', 'GST'])
    for c in qs:
        writer.writerow([c.customer_name, c.customer_address or '', c.customer_phone or '', c.customer_gst or ''])
    return response


@login_required
def customer_add(request):
    app_on = app_enabled(request.user)
    context = {'customer_app_enabled': app_on}
    if request.method == "POST":
        customer_form = CustomerForm(request.POST, user=request.user)
        if request.POST.get('customer_phone') == "":
            context["error_message"] = "Customer phone is required."
        elif Customer.objects.filter(user=request.user, customer_phone=request.POST.get('customer_phone')).exists():
            context["error_message"] = "Customer with this phone number already exists."
        elif customer_form.is_valid():
            new_customer = customer_form.save(commit=False)
            new_customer.user = request.user
            # Only a business with the customer app switched on can show a customer in it.
            new_customer.is_mobile_user = app_on and request.POST.get('is_mobile_user') == 'on'
            new_customer.save()
            add_customer_book(new_customer)
            return redirect('customers')
        context['customer_form'] = customer_form
        context['is_mobile_user'] = app_on and request.POST.get('is_mobile_user') == 'on'
        return render(request, 'customers/customer_edit.html', context)
    context['customer_form'] = CustomerForm(user=request.user)
    context['is_mobile_user'] = False
    return render(request, 'customers/customer_edit.html', context)


@login_required
def customer_edit(request, customer_id):
    customer_obj = get_object_or_404(Customer, user=request.user, id=customer_id)
    app_on = app_enabled(request.user)
    was_visible = customer_obj.is_mobile_user
    context = {'customer_app_enabled': app_on, 'customer_id': customer_id, 'id': customer_obj.id}
    if request.method == "POST":
        customer_form = CustomerForm(request.POST, instance=customer_obj, user=request.user)
        # With the customer app off the toggle isn't on the form, so keep the stored value
        # rather than reading a missing checkbox as "off".
        wants_visible = (request.POST.get('is_mobile_user') == 'on') if app_on else was_visible
        if request.POST.get('customer_phone') == "":
            context["error_message"] = "Customer phone is required."
        elif Customer.objects.filter(user=request.user,
                customer_phone=request.POST.get('customer_phone')).exclude(id=customer_id).exists():
            context["error_message"] = "Customer with this phone number already exists."
        elif customer_form.is_valid():
            new_customer = customer_form.save(commit=False)
            new_customer.is_mobile_user = wants_visible
            new_customer.save()
            if wants_visible != was_visible:
                refresh_for_customer(new_customer)
            return redirect('customers')
        context['customer_form'] = customer_form
        context['is_mobile_user'] = wants_visible
        return render(request, 'customers/customer_edit.html', context)
    context['customer_form'] = CustomerForm(instance=customer_obj, user=request.user)
    context['is_mobile_user'] = customer_obj.is_mobile_user
    return render(request, 'customers/customer_edit.html', context)


@login_required
def customer_delete(request):
    if request.method == "POST":
        customer_id = request.POST["customer_id"]
        customer_obj = get_object_or_404(Customer, user=request.user, id=customer_id)
        party = party_for(customer_obj)
        customer_obj.delete()
        if party is not None:
            refresh_login(party)          # it may have been their last visible ledger
    return redirect('customers')


@login_required
def customers_collection_calendar(request):
    context = {}
    case_mapping = dict(Customer.DAYS)
    filter_day = request.GET.get('filter')
    # Default to current day if no filter specified
    if filter_day is None:
        # Python: Monday=0..Sunday=6 → Model: Sunday=0, Monday=1..Saturday=6
        py_day = timezone.localtime(timezone.now()).weekday()
        filter_day = str((py_day + 1) % 7)
        context['default_filter'] = True
    queryset = Book.objects.filter(user=request.user).exclude(customer_id__isnull=True).order_by('customer__customer_name')
    if filter_day:
        queryset = queryset.filter(customer__collection_day=filter_day).order_by('customer__book__current_balance')
        context['filter_day_display'] = case_mapping.get(int(filter_day))
    context['filter_day'] = filter_day
    context['books'] = queryset
    return render(request, 'customers/collection_calendar.html', context)


# ================= Customer API Views ===========================
@login_required
def customersjson(request):
    customers = list(Customer.objects.filter(user=request.user).values())
    return JsonResponse(customers, safe=False)



@login_required
@require_POST
def customer_is_mobile_user(request):
    """Turn this business's ledger on or off in the customer's app.

    Keyed by the customer's id - the old per-customer login ID is gone. A business can
    only toggle its OWN customer, and only once GSTSync has switched the customer app on
    for it; the customer's login itself is issued by GSTSync."""
    customer_id = (request.POST.get("customer_id") or "").strip()
    if not customer_id.isdigit():
        return JsonResponse({'status': 'error', 'message': 'Customer is required.'})
    customer_obj = Customer.objects.filter(id=int(customer_id), user=request.user).first()
    if customer_obj is None:
        return JsonResponse({'status': 'error', 'message': 'Customer not found.'})
    if not app_enabled(request.user):
        return JsonResponse({'status': 'error',
                             'message': "The customer app isn't switched on for your business."})
    customer_obj.is_mobile_user = not customer_obj.is_mobile_user
    customer_obj.save(update_fields=["is_mobile_user"])
    refresh_for_customer(customer_obj)
    state = "on" if customer_obj.is_mobile_user else "off"
    return JsonResponse({'status': 'success',
                         'message': f'Mobile access for {customer_obj.customer_name} is now {state}.'})

@login_required
@require_POST
def customer_collection_day_update(request):
    customer_id = (request.POST.get("customer_id") or "").strip()
    place = request.POST.get("customer_place", None)
    day = request.POST.get("collection_day", 0)
    if not customer_id.isdigit():
        return JsonResponse({'status': 'error', 'message': 'Customer ID is required.'})
    # Scoped to this business - a business can only update its OWN customer.
    customer_obj = Customer.objects.filter(id=int(customer_id), user=request.user).first()
    if customer_obj is None:
        return JsonResponse({'status': 'error', 'message': 'Customer not found.'})
    customer_obj.collection_day = day
    customer_obj.customer_place = place
    customer_obj.save()
    return JsonResponse({'status': 'success', 'message': 'Customer collection day & place updated.'})


def show_customer_collection_api(request):
    markdown = request.GET.get('markdown', 'false').lower() == 'true'
    user_id = request.GET.get('user_id', None)
    today = timezone.localtime().weekday()
    collection_day = (today + 1) % 7
    collection_day_name = Customer.DAYS[collection_day][1]
    books = Book.objects.filter(user_id=user_id, customer__collection_day=collection_day)\
        .exclude(customer_id__isnull=True)\
        .order_by('current_balance')

    data = []
    markdown_blocks = []
    separator = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
    counter = 1
    
    markdown_blocks.append(f"📅  _*COLLECTION ROUTE* \\- *{_escape_md(collection_day_name)}*_\n")
    if not books.exists():
        markdown_blocks.append(f"_No customers with collection day on {_escape_md(collection_day_name)}\\._")
    for book in books:
        customer = book.customer
        current_balance = -round(book.current_balance or 0, 2)
        data.append({
            'current_balance': current_balance,
            'customer_name': customer.customer_name,
            'customer_place': customer.customer_place,
            'collection_day': customer.collection_day,
        })
        markdown_blocks.append(f"{counter}\\. *{_escape_md(customer.customer_name)}*")
        if customer.customer_place:
            markdown_blocks.append(f"    📍  *{_escape_md(customer.customer_place)}*")
        markdown_blocks.append(f"    💰  *₹{_escape_md(str(current_balance))}*\n")
        counter += 1
    # ── Footer ──
    markdown_blocks.append(separator)
    markdown_blocks.append(f'🦀  _Crab AI \\| {_escape_md(timezone.localtime().strftime("%d %b %Y"))}_')
    markdown_formatted = '\n'.join(markdown_blocks)
    if markdown:
        markdown_data = {
            'markdown': markdown_formatted,
            'count': len(books),
        }
        return JsonResponse(markdown_data, safe=False)
    return JsonResponse(data, safe=False)
