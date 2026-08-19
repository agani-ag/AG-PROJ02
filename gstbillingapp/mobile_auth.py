"""
Signed-token auth + multi-business resolution for the mobile web pages (/m/).

gstbilling mints an unforgeable Django-signed token identifying a Customer or an
Employee. Both can span several businesses in the same GST group:

  * Employee — the explicitly chosen `businesses` set (falls back to the home business).
  * Customer — their records across the group, matched by phone.

A `?biz=<id>` switch (validated against the accessible set) picks the active business;
screens scope to it. The `v` version stamp is enforced so bumping the record's version
revokes one link and its live session.
"""
from functools import wraps

from django.core import signing
from django.contrib.auth.models import User
from django.shortcuts import render, redirect

from .models import Customer, Employee, UserProfile

_SALT = "gstbillingapp.mobile.v2"

# The magic-link identity is kept in its OWN cookie, not the shared Django session,
# so a desktop logout / user-switch in the same browser can't sign the phone out.
# It carries the signed token itself (unforgeable), refreshed on every hit for a
# sliding window; a version bump still revokes it via _load_identity().
_COOKIE = "m_auth"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


# ---------------- minting ----------------
def mint_customer_token(customer):
    return signing.dumps({"r": "c", "id": customer.id, "v": customer.mobile_token_version}, salt=_SALT)


def mint_employee_token(employee):
    return signing.dumps({"r": "emp", "id": employee.id, "v": employee.token_version}, salt=_SALT)


def verify_mobile_token(token, max_age=None):
    if not token:
        return None
    try:
        return signing.loads(token, salt=_SALT, max_age=max_age)
    except signing.BadSignature:
        return None


# ---------------- business group ----------------
# ---------------- identity + accessibility ----------------
def _load_identity(payload):
    if not payload:
        return None
    role, rid, ver = payload.get("r"), payload.get("id"), payload.get("v")
    if role == "c":
        c = Customer.objects.select_related("user").filter(id=rid).first()
        if c and c.user and c.mobile_token_version == ver:
            return {"role": "customer", "primary": c}
    elif role == "emp":
        emp = Employee.objects.select_related("business").filter(id=rid, is_active=True).first()
        if emp and emp.token_version == ver:
            return {"role": "employee", "employee": emp}
    return None


def _accessible(identity):
    """Return (list of business Users, {business_id: sibling Customer} for customers)."""
    if identity["role"] == "employee":
        return list(identity["employee"].covered_businesses()), {}
    # A customer's records are the same real customer wherever their GSTIN matches —
    # matched by customer_gst across ALL businesses (not limited to a GST group).
    primary = identity["primary"]
    gst = (primary.customer_gst or "").strip()
    if gst:
        siblings = list(Customer.objects.select_related("user").filter(customer_gst=gst))
    else:
        siblings = [primary]
    if primary.id not in [s.id for s in siblings]:
        siblings.append(primary)
    by_business = {s.user_id: s for s in siblings if s.user_id}
    return list(User.objects.filter(id__in=list(by_business.keys()))), by_business


def resolve_mobile_actor(request):
    # Priority: a fresh ?t= link → the durable m_auth cookie → the legacy session.
    token = request.GET.get("t") or request.COOKIES.get(_COOKIE)
    payload = verify_mobile_token(token)
    identity = _load_identity(payload) if payload else None
    if identity and token:
        # Remember it so the decorator can (re)persist the cookie on the response.
        request._mobile_token = token

    if not identity:
        # Backward-compat: sessions established before the m_auth cookie existed.
        kind, rid = request.session.get("m_kind"), request.session.get("m_id")
        if kind and rid is not None:
            identity = _load_identity({"r": kind, "id": rid, "v": request.session.get("m_v")})

    if not identity:
        return None

    businesses, by_business = _accessible(identity)
    if not businesses:
        return None

    # Resolve the active business (?biz → session → first).
    biz_ids = [b.id for b in businesses]
    req_biz = request.GET.get("biz")
    if req_biz and req_biz.isdigit() and int(req_biz) in biz_ids:
        active_id = int(req_biz)
    elif request.session.get("m_biz") in biz_ids:
        active_id = request.session["m_biz"]
    else:
        active_id = biz_ids[0]
    request.session["m_biz"] = active_id
    active_business = next(b for b in businesses if b.id == active_id)

    actor = {
        "role": identity["role"],
        "businesses": businesses,
        "active_business": active_business,
        "multi": len(businesses) > 1,
        "user": active_business,
    }
    if identity["role"] == "employee":
        actor["employee"] = identity["employee"]
    else:
        actor["primary"] = identity["primary"]
        actor["siblings"] = by_business
        actor["customer"] = by_business.get(active_id) or identity["primary"]
    return actor


def mobile_login_required(role=None):
    def _decorator(view):
        @wraps(view)
        def _wrapped(request, *args, **kwargs):
            actor = resolve_mobile_actor(request)
            if not actor or (role and actor["role"] != role):
                return render(request, "m/denied.html", status=403)
            request.mobile_actor = actor

            if request.GET.get("t"):
                resp = redirect(request.path)  # drop token from URL/history
            else:
                resp = view(request, *args, **kwargs)

            # (Re)persist the durable auth cookie so a lost session self-heals and the
            # sliding window keeps a regular user signed in. httponly: JS can't read it;
            # secure only on HTTPS so dev over HTTP still works.
            token = getattr(request, "_mobile_token", None)
            if token:
                resp.set_cookie(_COOKIE, token, max_age=_COOKIE_MAX_AGE,
                                httponly=True, samesite="Lax", secure=request.is_secure())
            return resp

        return _wrapped

    return _decorator
