"""
Signed-token auth + account resolution for the mobile web pages (/m/).

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

A customer's screens are scoped to one ACCOUNT: one of their visible customer rows.
Usually that's one row per business, but a business can hold two rows for the same owner
(two shops, two firms), and each is its own ledger — so the customer switches between
rows, not businesses. `?acct=<row id>` picks one (validated against the person's own
rows); the older `?biz=<id>` still works and picks that business's account. Employees
switch businesses with `?biz=`. The `v` version stamp is enforced so bumping the record's
version revokes one link and its live session.
"""
from collections import defaultdict
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


# ---------------- account labels ----------------
def _brand(user):
    p = getattr(user, "userprofile", None)
    return ((p.business_brand or p.business_title) if p else None) or user.username


def label_accounts(rows):
    """One entry per customer row, in the order given: {row, chip, brand, detail}.

    A business holding one row for this person is labelled by its brand alone — exactly
    as before. Only when a business holds two or more of their rows does the chip add
    what tells them apart: the place, else the name on that business's books, else the
    row number. `detail` ("KMR TRADERS, ERODE") is the longer line for list screens.
    Used by the customer's own app and by the staff app's switcher, so both read alike."""
    rows = list(rows)
    at_business = defaultdict(list)
    for r in rows:
        at_business[r.user_id].append(r)
    out = []
    for r in rows:
        brand = _brand(r.user)
        same = at_business[r.user_id]
        if len(same) == 1:
            out.append({"row": r, "chip": brand, "brand": brand, "detail": ""})
            continue
        place = (r.customer_place or "").strip()
        name = (r.customer_name or "").strip()
        places = [(s.customer_place or "").strip().upper() for s in same]
        names = [(s.customer_name or "").strip().upper() for s in same]
        if place and places.count(place.upper()) == 1:
            tell = place
        elif name and names.count(name.upper()) == 1:
            tell = name
        else:
            tell = "#%d" % r.id
        out.append({"row": r, "chip": "%s · %s" % (brand, tell), "brand": brand,
                    "detail": ", ".join(x for x in (name, place) if x)})
    return out


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
    """Return (business Users, visible customer rows). Rows are empty for employees."""
    if identity["role"] == "employee":
        return list(identity["employee"].covered_businesses()), []
    if identity.get("party") is not None:
        rows = visible_rows(identity["party"])          # ordered by business, then row
    else:
        # An older single-row link: that row only, and only while its business shows it.
        primary = identity["primary"]
        rows = [primary] if row_is_visible(primary) else []
    # No business left means every one has switched this customer off - the caller shows
    # the "deactivated" screen rather than "expired".
    businesses = list(User.objects.filter(id__in={r.user_id for r in rows})
                      .select_related("userprofile").order_by("id"))
    return businesses, rows


def _pick_account(request, rows, req_biz):
    """The customer row to show: ?acct → an older ?biz link → the remembered account →
    the remembered business → the first."""
    by_id = {r.id: r for r in rows}
    req = request.GET.get("acct")
    if req and req.isdigit() and int(req) in by_id:
        return by_id[int(req)]
    current = by_id.get(request.session.get("m_acct"))
    if req_biz is not None:
        # ?biz= links predate accounts: stay on the current account if it's at that
        # business, otherwise open that business's first.
        if current is not None and current.user_id == req_biz:
            return current
        return next(r for r in rows if r.user_id == req_biz)
    if current is not None:
        return current
    at_biz = [r for r in rows if r.user_id == request.session.get("m_biz")]
    return at_biz[0] if at_biz else rows[0]


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

    businesses, rows = _accessible(identity)
    if not businesses:
        # The person is known, but every business has turned their mobile access off.
        # That's a deactivation, not an expiry — tell them to contact the business.
        request._mobile_denied = "deactivated"
        return None

    by_biz = {b.id: b for b in businesses}
    req_biz = request.GET.get("biz")
    req_biz = int(req_biz) if req_biz and req_biz.isdigit() and int(req_biz) in by_biz else None

    if identity["role"] == "employee":
        # Resolve the active business (?biz → session → first).
        if req_biz is not None:
            active_id = req_biz
        elif request.session.get("m_biz") in by_biz:
            active_id = request.session["m_biz"]
        else:
            active_id = businesses[0].id
        request.session["m_biz"] = active_id
        active_business = by_biz[active_id]
        emp = identity["employee"]
        # is_admin (and salary/attendance) are per-business: read the ACTIVE posting.
        posting = emp.postings.filter(business_id=active_id).first()
        return {
            "role": "employee",
            "businesses": businesses,
            "active_business": active_business,
            "multi": len(businesses) > 1,
            "user": active_business,
            # The chip row at the top of every screen (m/base.html).
            "switch": [{"param": "biz=%d" % b.id, "label": _brand(b), "on": b.id == active_id}
                       for b in businesses],
            "employee": emp,
            "posting": posting,
            "is_admin": bool(posting and posting.is_admin),
        }

    # Customer: every visible row is an account; screens scope to the active one.
    accounts = label_accounts(rows)
    active = _pick_account(request, rows, req_biz)
    request.session["m_acct"] = active.id
    request.session["m_biz"] = active.user_id
    active_business = by_biz[active.user_id]
    return {
        "role": "customer",
        "businesses": businesses,
        "active_business": active_business,
        "user": active_business,
        "accounts": accounts,
        "multi": len(accounts) > 1,
        "switch": [{"param": "acct=%d" % a["row"].id, "label": a["chip"],
                    "on": a["row"].id == active.id} for a in accounts],
        "customer": active,
        # A Party login has no single "primary" row, so its first visible row stands in
        # for the greeting; everything else works from the ACTIVE account.
        "primary": identity.get("primary") or rows[0],
        "party": identity.get("party"),
    }


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
