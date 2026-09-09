"""Business lifecycle operations for the operator console.

Kept out of the views so each one is directly testable and can be reused from a
management command.

The important subtlety is deletion. Almost every model scopes to its business with
`user = ForeignKey(User, null=True, on_delete=SET_NULL)`, so simply deleting the auth.User
does NOT remove that business's data — it silently blanks the owner and leaves the rows
behind as untenanted orphans. (That is exactly how 48 orphaned invoices appeared in this
database once before.) purge_business() therefore deletes the rows explicitly, and only
then the user.

Which tables those are is DERIVED from the model graph rather than listed by hand, so
adding a model needs no change here — see owned_lookups().
"""
from django.apps import apps
from django.contrib.auth.models import User
from django.db import models, transaction
from django.db.models import Count, Max, Q

from .models import ActiveDevice, Book, Customer, Invoice, Product, UserProfile


# --------------------------------------------------------------------------- #
# What a business owns — DERIVED, never hand-listed
# --------------------------------------------------------------------------- #
# The set of tables is worked out from the model graph at runtime rather than written
# out here, because a hand-maintained list silently goes stale: add a model, forget this
# file, and purge quietly leaves its rows behind forever. (ActiveDevice was added late
# and had to be remembered; the next one would not be.)
#
# The rule has two steps:
#
#   1. ROOTS — any model with a ForeignKey to auth.User named `user` or `business`. That
#      field IS the tenancy column throughout this app.
#   2. CHILDREN — any model with a CASCADE ForeignKey to something already owned, walked
#      to closure. BookLog hangs off Book, AttendanceLog off EmployeePosting, and so on.
#
# Filters compose down the chain, so BookLog resolves to parent_book__user and
# AttendanceLog to posting__business — exactly the lookups that used to be written by
# hand, but derived, so they cannot drift from the models.

# Field names that mean "this row belongs to that business".
_OWNERSHIP_FIELD_NAMES = {"user", "business"}

# FKs to auth.User that are a REFERENCE, not ownership. Deleting by these would remove
# another business's rows. Anything pointing at User and not covered by either set makes
# ConsolePurgeCoverageTests fail, so a new one has to be classified deliberately.
_NOT_OWNERSHIP = {
    ("Quotation", "converted_by"),   # which operator converted it, not who owns it
}


def _app_models():
    return sorted(apps.get_app_config("gstbillingapp").get_models(),
                  key=lambda m: m.__name__)


def _fks(model):
    for f in model._meta.get_fields():
        if isinstance(f, (models.ForeignKey, models.OneToOneField)):
            yield f


def user_fk_fields():
    """Every (model, field) in this app pointing at auth.User. Used by the coverage test."""
    for model in _app_models():
        for f in _fks(model):
            if f.related_model is User:
                yield model, f


def owned_lookups():
    """{model: lookup} where lookup is the ORM path from that model to its owning User.

    Derived from the model graph — see the note above. Deterministic: models are walked
    in name order, so the same lookup is chosen on every run.
    """
    lookups = {}
    for model, f in user_fk_fields():
        if f.name in _OWNERSHIP_FIELD_NAMES:
            lookups[model] = f.name

    # Walk CASCADE children to closure.
    changed = True
    while changed:
        changed = False
        for model in _app_models():
            if model in lookups:
                continue
            for f in _fks(model):
                parent = lookups.get(f.related_model)
                if parent is not None and f.remote_field.on_delete is models.CASCADE:
                    lookups[model] = "%s__%s" % (f.name, parent)
                    changed = True
                    break
    return lookups


def owned_querysets(user):
    """(label, queryset) for every table this business owns, longest lookup first.

    Deepest-first is cosmetic — every cross-model reference in this app is CASCADE or
    SET_NULL, so Django resolves either way — but it keeps the delete order stable and
    the preview reading child-before-parent.
    """
    lookups = owned_lookups()
    ordered = sorted(lookups.items(),
                     key=lambda kv: (-kv[1].count("__"), kv[0].__name__))
    return [(m._meta.model_name, m.objects.filter(**{lk: user})) for m, lk in ordered]


def business_footprint(user):
    """Row counts this business owns. Used by the purge preview, so what you are shown is
    exactly what would go."""
    return {label: qs.count() for label, qs in owned_querysets(user)}


def business_summary(user):
    """One row for the console list."""
    profile = getattr(user, "userprofile", None)
    invoices = Invoice.objects.filter(user=user)
    return {
        "user": user,
        "profile": profile,
        "title": (profile.business_title if profile else "") or "",
        "brand": (profile.business_brand if profile else "") or "",
        "gst": (profile.business_gst if profile else "") or "",
        "invoices": invoices.count(),
        "customers": Customer.objects.filter(user=user).count(),
        "products": Product.objects.filter(user=user).count(),
        "last_invoice": invoices.aggregate(d=Max("invoice_date"))["d"],
        "is_active": user.is_active,
        "joined": user.date_joined,
    }


@transaction.atomic
def create_business(*, username, password, title, brand="", gst="", phone="", email="",
                    address="", created_by=None):
    """Create a business login plus its profile, together or not at all.

    Replaces the old public signup: the same two objects, but only an operator can make
    them, and the profile is never left missing (signup could half-succeed and leave a
    User with no UserProfile, which breaks every business screen).
    """
    user = User.objects.create_user(username=username, password=password)
    profile = UserProfile.objects.create(
        user=user,
        business_title=title or None,
        business_brand=brand or None,
        business_gst=gst or None,
        business_phone=phone or None,
        business_email=email or None,
        business_address=address or None,
    )
    return user, profile


def set_business_active(user, active):
    """Suspend or restore a business. Django's auth backend already refuses login for an
    inactive user, so this needs nothing else to take effect."""
    user.is_active = bool(active)
    user.save(update_fields=["is_active"])
    # Drop their live device rows so the presence count doesn't show a suspended business
    # as online.
    if not active:
        ActiveDevice.objects.filter(user=user).delete()
    return user


def reset_business_password(user, password):
    user.set_password(password)
    user.save(update_fields=["password"])
    # Any existing browser session keeps working off its session cookie otherwise.
    ActiveDevice.objects.filter(user=user).delete()
    return user


@transaction.atomic
def purge_business(user, commit=True):
    """Delete a business and everything it owns. Irreversible.

    Returns the per-table counts removed (or that would be, with commit=False). The rows
    are deleted explicitly rather than relying on the User delete, because the owning FKs
    are SET_NULL and would otherwise leave the data behind with no owner.
    """
    counts = business_footprint(user)
    # Total the row counts BEFORE the non-count keys go in. Python's bool is a subclass
    # of int, so a naive sum() over the finished dict counts `committed: True` as a row.
    total = sum(counts.values())
    if commit:
        for _, qs in owned_querysets(user):
            qs.delete()
        # UserProfile is itself a derived root (user, CASCADE), so it went with the loop.
        user.delete()
    return dict(counts, username=user.username, committed=bool(commit), total=total)


# --------------------------------------------------------------------------- #
# Cross-business customer identity
# --------------------------------------------------------------------------- #
# The same real customer is a SEPARATE Customer row in each business that sells to them —
# there is no shared customer table — so the console has to work out which rows are the
# same person. In this data 218 rows are 158 real people: 41 of them buy from more than
# one of the businesses.
#
# The key reuses what the app already believes rather than inventing a third rule:
#
#   1. GSTIN — mobile_auth._accessible() already treats a matching customer_gst as the
#      same customer across businesses; that is what lets one person see all their
#      ledgers in the app. 80% of rows carry one.
#   2. phone — for the 20% with no GSTIN (retail buyers). Every row in this database has
#      a phone, so between the two nothing falls through. Compared on the last 10 digits
#      so +91/0 prefixes and spacing do not split a person in two.
#   3. name — last resort, matching find_matching_customer()'s within-business rule.
#
# Deliberately NOT fuzzy: a wrong merge silently shows one business's ledger under
# another's customer, which is worse than showing two rows.
def customer_identity(customer):
    """(kind, value) identifying the real person behind a Customer row."""
    gst = (customer.customer_gst or "").strip().upper()
    if gst:
        return ("gst", gst)
    digits = "".join(ch for ch in (customer.customer_phone or "") if ch.isdigit())
    if digits:
        return ("phone", digits[-10:])
    return ("name", (customer.customer_name or "").strip().upper())


def customer_people(q=""):
    """Every customer across every business, grouped into real people.

    Returns a list of dicts, one per person, each carrying the individual per-business
    records. Sorted by how many businesses they appear in, so the shared ones — the point
    of the screen — are at the top.
    """
    from collections import OrderedDict

    rows = (Customer.objects
            .select_related("user", "user__userprofile")
            .order_by("customer_name", "id"))
    if q:
        rows = rows.filter(
            Q(customer_name__icontains=q) | Q(customer_phone__icontains=q)
            | Q(customer_gst__icontains=q))
    rows = list(rows)

    # One query for every ledger, then matched in memory — a per-row lookup would be
    # hundreds of queries on this screen.
    balances = {}
    for book in Book.objects.filter(customer__in=rows).only("customer_id", "current_balance"):
        balances[book.customer_id] = float(book.current_balance or 0)

    invoice_counts = dict(
        Invoice.objects.filter(invoice_customer__in=rows)
        .values_list("invoice_customer")
        .annotate(n=Count("id"))
        .values_list("invoice_customer", "n"))

    people = OrderedDict()
    for c in rows:
        key = customer_identity(c)
        person = people.setdefault(key, {
            "key": key, "kind": key[0], "value": key[1],
            "name": c.customer_name or "",
            "phone": c.customer_phone or "",
            "gst": c.customer_gst or "",
            "records": [], "business_ids": set(),
            "invoices": 0, "owed": 0.0, "advance": 0.0,
        })
        balance = balances.get(c.id, 0.0)
        invoices = invoice_counts.get(c.id, 0)
        profile = getattr(c.user, "userprofile", None)
        person["records"].append({
            "customer": c,
            "business": c.user,
            "brand": (profile.business_brand if profile else "") or "",
            "title": (profile.business_title if profile else "") or "",
            "balance": balance,
            "owed": -balance if balance < 0 else 0.0,
            "invoices": invoices,
        })
        if c.user_id:
            person["business_ids"].add(c.user_id)
        person["invoices"] += invoices
        if balance < 0:
            person["owed"] += -balance
        else:
            person["advance"] += balance
        # Keep the fullest identity on the person, not whichever row happened to be first.
        if not person["gst"] and c.customer_gst:
            person["gst"] = c.customer_gst
        if not person["phone"] and c.customer_phone:
            person["phone"] = c.customer_phone

    out = list(people.values())
    for p in out:
        p["business_count"] = len(p["business_ids"])
        p["shared"] = p["business_count"] > 1
        p["record_count"] = len(p["records"])
    out.sort(key=lambda p: (-p["business_count"], -p["owed"], p["name"]))
    return out


def customer_person_for(customer):
    """The one person group a given Customer row belongs to — used by the detail screen."""
    key = customer_identity(customer)
    for person in customer_people():
        if person["key"] == key:
            return person
    return None
