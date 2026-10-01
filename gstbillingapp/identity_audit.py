"""What stands between the data and a working app login — read-only, always.

The old console asked an admin to decide who was who. It doesn't any more: the number decides.
So the console's job is now to show the handful of rows where the number can't do that, which is
what this finds:

  * rows with **no usable mobile** — a landline, two numbers in one box, or nothing;
  * the same number on **two customers of one business**, which has to be fixed — inside one
    business a number can only be one customer;
  * the same number **across businesses** — not a fault, that's the join, but worth reading once;
  * rows carrying the **business's own** number or email, the classic way to merge every
    customer of a shop into one person;
  * people whose number and email point at **two different SyncUp users**.

Nothing here changes anything.
"""
from collections import defaultdict

from django.contrib.auth.models import User

from .identity import clean_email, clean_mobile
from .models import AppUser, Customer, Employee, UserProfile


def _brand(user):
    profile = getattr(user, "userprofile", None)
    return ((profile.business_brand or profile.business_title) if profile else "") or user.username


def unusable_rows(business=None):
    """Customer rows whose phone can't be an identity — no app login until it is fixed."""
    rows = Customer.objects.select_related("user", "user__userprofile")
    if business is not None:
        rows = rows.filter(user=business)
    out = []
    for c in rows:
        if clean_mobile(c.customer_phone) or clean_email(c.customer_email):
            continue
        out.append({"row": c, "brand": _brand(c.user) if c.user_id else "—",
                    "phone": c.customer_phone or "", "why": (
                        "No number at all" if not (c.customer_phone or "").strip()
                        else "Not a 10-digit Indian mobile")})
    return out


def _by_identifier(business=None):
    rows = Customer.objects.select_related("user", "user__userprofile", "app_user")
    if business is not None:
        rows = rows.filter(user=business)
    seen = defaultdict(list)
    for c in rows:
        mobile = clean_mobile(c.customer_phone)
        if mobile:
            seen[mobile].append(c)
    return seen


def duplicates_in_business(business=None):
    """One number, two customers of the same business — the rows that would merge two people
    into one app user."""
    clashes = []
    for mobile, rows in _by_identifier(business).items():
        per_business = defaultdict(list)
        for c in rows:
            per_business[c.user_id].append(c)
        for user_id, group in per_business.items():
            if len(group) < 2:
                continue
            clashes.append({"mobile": mobile, "brand": _brand(group[0].user), "rows": group})
    return clashes


def shared_across_businesses():
    """One number in several businesses — the joins that will happen. Not faults.

    Each entry carries the shop name as **each** business keeps it, because that is the part
    worth reading: the same number under three different spellings is how you tell a real join
    from a number typed into the wrong row."""
    out = []
    for mobile, rows in _by_identifier().items():
        businesses = {c.user_id for c in rows}
        if len(businesses) < 2:
            continue
        person = next((c.app_user for c in rows if c.app_user_id), None)
        entries = sorted(({"brand": _brand(c.user) if c.user_id else "—",
                           "name": c.customer_name or "(no name)",
                           "place": c.customer_place or ""} for c in rows),
                         key=lambda e: e["brand"])
        names = {e["name"].strip().upper() for e in entries}
        out.append({
            "mobile": mobile, "rows": rows, "person": person, "entries": entries,
            "name": (person.name if person and person.name else entries[0]["name"]),
            "one_name": len(names) == 1,
            "brands": sorted({e["brand"] for e in entries}),
        })
    return sorted(out, key=lambda s: s["name"].upper())


def business_own_contact():
    """Rows carrying their own business's number or email — one typo away from making every
    customer of that shop the same person."""
    own = {}
    for profile in UserProfile.objects.select_related("user"):
        own[profile.user_id] = (clean_mobile(profile.business_phone),
                                clean_email(profile.business_email))
    out = []
    for c in Customer.objects.select_related("user", "user__userprofile"):
        mobile, email = own.get(c.user_id, ("", ""))
        if (mobile and clean_mobile(c.customer_phone) == mobile) or \
                (email and clean_email(c.customer_email) == email):
            out.append({"row": c, "brand": _brand(c.user)})
    return out


def conflicts():
    """A row whose number belongs to one person and whose email belongs to another."""
    out = []
    for c in Customer.objects.select_related("user", "app_user"):
        mobile, email = clean_mobile(c.customer_phone), clean_email(c.customer_email)
        if not mobile or not email:
            continue
        by_mobile = AppUser.objects.filter(mobile=mobile).first()
        by_email = AppUser.objects.filter(email=email).first()
        if by_mobile and by_email and by_mobile.id != by_email.id:
            out.append({"row": c, "brand": _brand(c.user) if c.user_id else "—",
                        "mobile_user": by_mobile, "email_user": by_email})
    return out


def staff_without_identity():
    """Employees who can't have a staff login, because there's no number to sign in with."""
    return [e for e in Employee.objects.select_related("business")
            if not clean_mobile(e.phone) and not clean_email(e.email)]


def summary(business=None):
    """Everything above, counted — what the console shows at a glance."""
    dupes = duplicates_in_business(business)
    unusable = unusable_rows(business)
    return {
        "unusable": unusable,
        "duplicates": dupes,
        "shared": shared_across_businesses() if business is None else [],
        "own_contact": business_own_contact() if business is None else [],
        "conflicts": conflicts() if business is None else [],
        "staff_without_identity": staff_without_identity() if business is None else [],
        "counts": {"unusable": len(unusable), "duplicates": len(dupes)},
    }
