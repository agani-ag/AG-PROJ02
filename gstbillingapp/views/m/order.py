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
from ...models import Customer, ProductCategory
from ...utils import cart_product_payload, create_cart_draft_quotation, CartError


def _business(request):
    # The active business (owner User) the actor is currently scoped to.
    return request.mobile_actor["user"]


@mobile_login_required()
def order(request):
    actor = request.mobile_actor
    business = _business(request)

    if actor["role"] == "customer":
        buyer = actor["customer"]
    else:
        # Employee must pick who the order is for. Launched with ?customer=<id>
        # from a customer's page; without it, show a quick picker.
        cid = request.GET.get("customer")
        if not (cid and cid.isdigit()):
            rows = [{"id": c.id, "name": c.customer_name, "phone": c.customer_phone}
                    for c in Customer.objects.filter(user=business).order_by("customer_name")]
            return render(request, "m/order_pick.html", {"rows": rows})
        buyer = get_object_or_404(Customer, id=int(cid), user=business)

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

    order_employee = None
    if actor["role"] == "customer":
        buyer = actor["customer"]
        allow_discount, created_by_customer, label = False, True, "customer"
        order_url = reverse("m_customer_orders")
    else:
        cid = payload.get("customer")
        try:
            buyer = Customer.objects.get(id=cid, user=business)
        except (Customer.DoesNotExist, ValueError, TypeError):
            return JsonResponse({"ok": False, "message": "Customer not found"}, status=400)
        allow_discount, created_by_customer, label = True, False, "employee"
        order_employee = actor.get("employee")     # credit the order to the field-staff
        order_url = reverse("m_employee_orders")

    try:
        result = create_cart_draft_quotation(
            business, items,
            existing_customer=buyer,
            is_gst=payload.get("is_gst", True),
            allow_discount=allow_discount,
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
