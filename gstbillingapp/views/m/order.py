"""
Mobile order flow (/m/order) — a lean, catalog-driven way to raise a DRAFT
quotation from the phone. Shared by both roles via the signed-token actor:

  * customer  — orders for themselves at the active business (no discounts).
  * employee  — orders on behalf of a chosen customer at the active business.

The catalog is rendered server-side (scoped + field-whitelisted, no cost price),
and every price is recomputed on checkout by create_cart_draft_quotation(), so a
tampered payload can never reprice a line or bill another business's customer.
"""
import json

from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from ...mobile_auth import mobile_login_required
from ...models import Customer, ProductCategory, Quotation
from ...utils import (cart_product_payload, create_cart_draft_quotation,
                      update_cart_draft_quotation, CartError)


def _business(request):
    # The active business (owner User) the actor is currently scoped to.
    return request.mobile_actor["user"]


def _buyer(request):
    """Resolve who the order is for. Returns (buyer, picker_response):

      * customer actor -> themselves, no picker.
      * employee -> the ?customer=<id> target; without it, (None, <picker page>) so
        the caller returns the picker for the employee to choose a customer.
    """
    actor = request.mobile_actor
    business = _business(request)
    if actor["role"] == "customer":
        return actor["customer"], None
    cid = request.GET.get("customer")
    if not (cid and cid.isdigit()):
        rows = [{"id": c.id, "name": c.customer_name, "phone": c.customer_phone}
                for c in Customer.objects.filter(user=business).order_by("customer_name")]
        return None, render(request, "m/order_pick.html", {"rows": rows})
    return get_object_or_404(Customer, id=int(cid), user=business), None


@mobile_login_required()
def order(request):
    actor = request.mobile_actor
    business = _business(request)
    buyer, picker = _buyer(request)
    if picker is not None:
        return picker

    categories = list(
        ProductCategory.objects.filter(user=business)
        .values("id", "category_name")
    )

    return render(request, "m/order.html", {
        "buyer": buyer,
        "role": actor["role"],
        "gst_available": bool((buyer.customer_gst or "").strip()),
        # Server-scoped, field-whitelisted catalog (no cost price).
        "products_json": json.dumps(cart_product_payload(business)),
        "categories_json": json.dumps(categories),
    })


@mobile_login_required()
def cart(request):
    """The e-commerce cart: review, edit quantities, remove lines, then place the order.
    Reads the same localStorage cart the catalog fills. ?edit=<id> re-opens a pending
    order for editing (its lines are loaded into the cart by the order-detail page)."""
    actor = request.mobile_actor
    business = _business(request)
    buyer, picker = _buyer(request)
    if picker is not None:
        return picker

    edit_id = ""
    eid = request.GET.get("edit")
    if eid and eid.isdigit():
        q = Quotation.objects.filter(id=int(eid), user=business, quotation_customer=buyer,
                                     status="DRAFT", created_from_cart=True).first()
        if q:
            edit_id = q.id

    return render(request, "m/cart.html", {
        "buyer": buyer,
        "role": actor["role"],
        "gst_available": bool((buyer.customer_gst or "").strip()),
        "products_json": json.dumps(cart_product_payload(business)),
        "edit_id": edit_id,
    })


def _order_scope(request, quotation_id):
    """A cart order this actor may see: their own (customer) or any of the business's
    cart orders (employee). Desktop-created quotations are never exposed on mobile.
    404 otherwise."""
    business = _business(request)
    qs = Quotation.objects.filter(id=quotation_id, user=business, created_from_cart=True)
    if request.mobile_actor["role"] == "customer":
        qs = qs.filter(quotation_customer=request.mobile_actor["customer"])
    return get_object_or_404(qs)


@mobile_login_required()
def order_detail(request, quotation_id):
    q = _order_scope(request, quotation_id)
    try:
        data = json.loads(q.quotation_json)
    except (ValueError, TypeError):
        data = {"items": []}
    # Map each saved line back to a product id so the cart can reopen it for editing.
    edit_lines = []
    for it in data.get("items", []):
        pid = it.get("product_id")
        edit_lines.append({"id": pid, "qty": it.get("invoice_qty", 0)})
    editable = q.status == "DRAFT" and q.created_from_cart
    return render(request, "m/order_detail.html", {
        "q": q, "d": data,
        "customer": q.quotation_customer.customer_name if q.quotation_customer else "N/A",
        "editable": editable,
        "edit_lines_json": json.dumps([l for l in edit_lines if l["id"]]),
        "role": request.mobile_actor["role"],
        "buyer_id": q.quotation_customer_id or "",
    })


@csrf_exempt
@mobile_login_required()
def order_update(request, quotation_id):
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "Invalid method"}, status=405)
    q = _order_scope(request, quotation_id)
    try:
        payload = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "message": "Malformed request"}, status=400)
    # Mobile orders never carry a manual discount — the product's own discount applies.
    try:
        result = update_cart_draft_quotation(
            q, payload.get("items") or [],
            is_gst=payload.get("is_gst", None), allow_discount=False,
        )
    except CartError as err:
        return JsonResponse({"ok": False, "message": str(err)}, status=400)
    label = ("" if result["is_gst"] else "QT-") + str(q.quotation_number)
    return JsonResponse({"ok": True, "quotation_id": q.id, "label": label,
                         "grand_total": result["totals"]["grand_total"],
                         "detail_url": reverse("m_order_detail", args=[q.id])})


@csrf_exempt
@mobile_login_required()
def order_cancel(request, quotation_id):
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "Invalid method"}, status=405)
    q = _order_scope(request, quotation_id)
    if q.status != "DRAFT" or not q.created_from_cart:
        return JsonResponse({"ok": False, "message": "This order can no longer be cancelled."}, status=400)
    q.delete()
    role = request.mobile_actor["role"]
    return JsonResponse({"ok": True, "order_url": reverse("m_customer_orders" if role == "customer" else "m_employee_orders")})


@csrf_exempt
@mobile_login_required()
def order_checkout(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "Invalid method"}, status=405)

    actor = request.mobile_actor
    business = _business(request)

    try:
        payload = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "message": "Malformed request"}, status=400)

    items = payload.get("items") or []

    # Mobile orders NEVER apply a manual discount — neither customer nor employee. The
    # product's own discount (Product table) is applied automatically by the engine when
    # allow_discount is False, so the price a buyer sees is the shop's own price.
    order_employee = None
    if actor["role"] == "customer":
        buyer = actor["customer"]
        created_by_customer, label = True, "customer"
        order_url = reverse("m_customer_orders")
    else:
        cid = payload.get("customer")
        try:
            buyer = Customer.objects.get(id=cid, user=business)
        except (Customer.DoesNotExist, ValueError, TypeError):
            return JsonResponse({"ok": False, "message": "Customer not found"}, status=400)
        created_by_customer, label = False, "employee"
        order_employee = actor.get("employee")     # credit the order to the field-staff
        order_url = reverse("m_employee_orders")

    try:
        result = create_cart_draft_quotation(
            business, items,
            existing_customer=buyer,
            is_gst=payload.get("is_gst", True),
            allow_discount=False,
            created_by_customer=created_by_customer,
            actor_label=label,
            order_employee=order_employee,
        )
    except CartError as err:
        return JsonResponse({"ok": False, "message": str(err)}, status=400)

    q = result["quotation"]
    return JsonResponse({
        "ok": True,
        "quotation_id": q.id,
        "label": ("" if result["is_gst"] else "QT-") + str(q.quotation_number),
        "gst_downgraded": result["gst_downgraded"],
        "grand_total": result["totals"]["grand_total"],
        "order_url": order_url,
    })
