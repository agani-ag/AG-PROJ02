"""
Signed-token auth + multi-business resolution for the mobile web pages (/m/).

gstbilling mints an unforgeable Django-signed token identifying a Party (one real shop
owner), a single Customer row, or an Employee:

  * Party — the customer rows a platform admin mapped together (see parties.py). Only
    rows whose business has the customer app on AND whose own mobile toggle is on are
    visible. This is the token the SyncUp app's link carries.
  * Customer row (older links) — that one row, in its own business only. It never
    expands to other businesses: GSTINs are printed on every invoice, so any business could
    put another business's customer's GSTIN on a row of its own. A shared GSTIN proves
    nothing; only the admin's mapping links businesses.
  * Employee — the businesses they're posted to (falls back to the home business).

A `?biz=<id>` switch (validated against the accessible set) picks the active business;
screens scope to it. The `v` version stamp is enforced so bumping the record's version
revokes one link and its live session.
"""
from functools import wraps

from django.core import signing
from django.contrib.auth.models import User
from django.shortcuts import render, redirect

from .models import Customer, Employee, Party, UserProfile
from .parties import row_is_visible, visible_rows

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


def mint_party_token(party):
    return signing.dumps({"r": "p", "id": party.id, "v": party.token_version}, salt=_SALT)


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
    if role == "p":
        party = Party.objects.filter(id=rid).first()
        if party and party.login_status == Party.LOGIN_ACTIVE and party.token_version == ver:
            return {"role": "customer", "party": party, "primary": None}
    elif role == "c":
        c = Customer.objects.select_related("user").filter(id=rid).first()
        if c and c.user and c.mobile_token_version == ver:
            return {"role": "customer", "primary": c}
    elif role == "emp":
        emp = Employee.objects.select_related("business").filter(id=rid, is_active=True).first()
        if emp and emp.token_version == ver:
            return {"role": "employee", "employee": emp}
    return None


def _accessible(identity):
    """Return (business Users, {business_id: that business's Customer row} for customers)."""
    if identity["role"] == "employee":
        return list(identity["employee"].covered_businesses()), {}
    if identity.get("party") is not None:
        rows = visible_rows(identity["party"])
    else:
        # An older single-row link: that row only, and only while its business shows it.
        primary = identity["primary"]
        rows = [primary] if row_is_visible(primary) else []
    by_business = {}
    for row in rows:
        by_business.setdefault(row.user_id, row)
    # No business left means every one has switched this customer off - the caller shows
    # the "deactivated" screen rather than "expired".
    businesses = list(User.objects.filter(id__in=list(by_business))
                      .select_related("userprofile").order_by("id"))
    return businesses, by_business


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
        # No/invalid/expired token or a revoked link — ask them to reopen from the app.
        request._mobile_denied = "expired"
        return None

    businesses, by_business = _accessible(identity)
    if not businesses:
        # The person is known, but every business has turned their mobile access off.
        # That's a deactivation, not an expiry — tell them to contact the business.
        request._mobile_denied = "deactivated"
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
        emp = identity["employee"]
        actor["employee"] = emp
        # is_admin (and salary/attendance) are per-business: read the ACTIVE posting.
        posting = emp.postings.filter(business_id=active_id).first()
        actor["posting"] = posting
        actor["is_admin"] = bool(posting and posting.is_admin)
    else:
        # A Party login has no single "primary" row, so its first visible row stands in;
        # screens mostly work from the ACTIVE business's row anyway.
        primary = identity.get("primary") or by_business[businesses[0].id]
        actor["primary"] = primary
        actor["party"] = identity.get("party")
        actor["siblings"] = by_business
        actor["customer"] = by_business.get(active_id) or primary
    return actor


def mobile_login_required(role=None):
    def _decorator(view):
        @wraps(view)
        def _wrapped(request, *args, **kwargs):
            actor = resolve_mobile_actor(request)
            if not actor or (role and actor["role"] != role):
                # "deactivated" only when the identity is valid but access was turned off;
                # a role mismatch or missing identity is the generic "expired" case.
                reason = getattr(request, "_mobile_denied", "expired") if not actor else "expired"
                return render(request, "m/denied.html", {"reason": reason}, status=403)
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
