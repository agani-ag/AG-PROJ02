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
from django.db.models import Max

from .models import ActiveDevice, Customer, Invoice, Product, UserProfile


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


def looks_like_test_data(summary):
    """A heuristic for the console to flag likely junk tenants — never an action on its
    own. A business with no GSTIN and almost nothing in it was probably a test signup."""
    return (not summary["gst"]) and summary["invoices"] <= 2 and summary["customers"] <= 2


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
