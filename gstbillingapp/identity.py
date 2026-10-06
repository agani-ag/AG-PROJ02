"""Who is who — the mobile number (or email) that makes two rows one person.

The rule, whole:

  * **The same mobile is the same person.** A customer row at three businesses carrying one
    number is one person with one app login. So is an employee at five. Nobody maps anyone;
    change the number on a row and the row moves to whoever holds the new one.
  * **An email works the same way** for the few who have one. Most customers have only a
    number, which is why the number leads.
  * **One identifier, one customer per business.** Across businesses it is the join; inside
    one business it would be two people sharing a ledger.
  * A row with neither has no app access. Nothing else about it changes.

The number is an Indian mobile, ten digits, stored bare. That is what SyncUp accepts as a
sign-in, and it refuses a landline — which is what stops a shop's shared line from turning five
customers into one person.
"""
import re

from django.db import transaction
from django.db.models import Q

from .models import AppUser, Customer, Employee

MOBILE = re.compile(r"^[6-9]\d{9}$")


# --------------------------------------------------------------------------- #
# Reading an identifier
# --------------------------------------------------------------------------- #
def clean_mobile(value):
    """An Indian mobile as bare 10 digits, or "" — never a guess.

    +91 and a leading 0 are dropped; anything else that isn't exactly one 10-digit number
    starting 6-9 (a landline, two numbers in one box, junk) is no identity at all."""
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if MOBILE.match(digits) else ""


def clean_email(value):
    email = (value or "").strip().lower()
    return email if "@" in email and "." in email.split("@")[-1] and " " not in email else ""


def mobile_error(value, *, required=True):
    """The message to show under the field, or "" when it's fine."""
    raw = str(value or "").strip()
    if not raw:
        return "Mobile number is required." if required else ""
    if clean_mobile(raw):
        return ""
    return ("Enter one 10-digit Indian mobile number (starting 6, 7, 8 or 9). A landline or two "
            "numbers can't be used.")


def identifiers(row):
    """(mobile, email) of a customer row or an employee — cleaned, either may be ""."""
    if isinstance(row, Customer):
        return clean_mobile(row.customer_phone), clean_email(row.customer_email)
    return clean_mobile(row.phone), clean_email(row.email)


def display_name(row):
    return (row.customer_name if isinstance(row, Customer) else row.name) or ""


# --------------------------------------------------------------------------- #
# One identifier, one customer per business
# --------------------------------------------------------------------------- #
def _clash(business, field, value, customer=None):
    """Another customer of this business already using this identifier — None when free."""
    if not value:
        return None
    rows = Customer.objects.filter(user=business).exclude(pk=customer.pk if customer else None)
    for row in rows.only("id", "customer_name", "customer_phone", "customer_email"):
        got = clean_mobile(row.customer_phone) if field == "mobile" else clean_email(row.customer_email)
        if got and got == value:
            return row
    return None


def customer_clash(business, *, mobile="", email="", customer=None):
    """(message, row) when this business already has someone else on that number or email."""
    for field, value, label in (("mobile", mobile, "mobile number"), ("email", email, "email")):
        row = _clash(business, field, value, customer)
        if row is not None:
            return ("%s already uses that %s. One %s belongs to one customer."
                    % (row.customer_name, label, label)), row
    return "", None


def employee_clash(business, *, mobile="", email="", employee=None):
    """The same rule for staff of one business."""
    rows = Employee.objects.filter(business=business).exclude(
        pk=employee.pk if employee else None)
    for row in rows:
        got_m, got_e = identifiers(row)
        if mobile and got_m == mobile:
            return "%s already uses that mobile number." % row.name, row
        if email and got_e == email:
            return "%s already uses that email." % row.name, row
    return "", None


# --------------------------------------------------------------------------- #
# Finding (or making) the person behind a row
# --------------------------------------------------------------------------- #
def find_person(mobile="", email=""):
    """The person holding either identifier — None if nobody does.

    Two different people can hold the two halves (a number one person owns, an email
    another's); that is a conflict the caller has to show rather than guess at."""
    if not mobile and not email:
        return None
    q = Q()
    if mobile:
        q |= Q(mobile=mobile)
    if email:
        q |= Q(email=email)
    found = list(AppUser.objects.filter(q)[:2])
    if len(found) > 1:
        raise Conflict("That mobile number and that email belong to two different app users.")
    return found[0] if found else None


class Conflict(Exception):
    """The row's number and email point at two different people."""


def _sole_owner(row):
    """The person this row already points at, when the row is all they are — nothing else
    points at them and they have an app login worth keeping. Otherwise None: a person two
    businesses share can't be re-numbered by one of them."""
    # Read it fresh: the copy hanging off the row was loaded before the login was opened.
    person = AppUser.objects.filter(pk=row.app_user_id).first() if row.app_user_id else None
    if person is None or not person.has_login:
        return None
    return person if _only_row_of(person, row) else None


def _only_row_of(person, row):
    """Is this row the only thing pointing at this person?

    It decides who may *correct* a number or an email rather than merely fill in a blank
    one. A person two businesses share can't have their sign-in rewritten by one of them —
    the other business would lose them — so there, the value entered first stands."""
    customers = (person.customers.exclude(pk=row.pk) if isinstance(row, Customer)
                 else person.customers.all())
    if customers.exists():
        return False
    employees = (person.employees.exclude(pk=row.pk) if isinstance(row, Employee)
                 else person.employees.all())
    return not employees.exists()


def person_for(row, *, create=True):
    """The AppUser this customer row or employee belongs to, making it if needed.

    Fills in a blank half (a person known by number who now has an email too) while it is
    still free, so the same person is found by either from then on."""
    mobile, email = identifiers(row)
    if not mobile and not email:
        return None
    person = find_person(mobile, email)
    if person is None:
        held = _sole_owner(row)
        if held is not None:
            # Their number was corrected and nobody else holds the new one. Move it on the same
            # person rather than making a second one: their app account, the password they may
            # have chosen and their history all survive a typo being fixed. The row carries a
            # note for identity_hooks, which tells SyncUp the sign-in has changed.
            held.mobile, held.email = mobile, email or None
            if display_name(row):
                held.name = display_name(row)
            held.identity_pending = True
            held.save(update_fields=["mobile", "email", "name", "identity_pending"])
            return held
        if not create:
            return None
        return AppUser.objects.create(mobile=mobile, email=email or None,
                                      name=display_name(row))
    # The person already exists. Two things can have happened to the row: a half they
    # didn't have was filled in (a number that now has an email beside it), or a half they
    # did have was corrected. Both have to land on the person — and both have to be told to
    # SyncUp, which is what identity_pending is for. Without it the email sat in our
    # database and never reached their app.
    alone = _only_row_of(person, row)
    fields = []
    if mobile and mobile != person.mobile and (alone or not person.mobile) \
            and not AppUser.objects.filter(mobile=mobile).exclude(pk=person.pk).exists():
        person.mobile, _ = mobile, fields.append("mobile")
    if email and email != person.email and (alone or not person.email) \
            and not AppUser.objects.filter(email=email).exclude(pk=person.pk).exists():
        person.email, _ = email, fields.append("email")
    if not person.name and display_name(row):
        person.name, _ = display_name(row), fields.append("name")
    if fields:
        person.identity_pending = True
        fields.append("identity_pending")
        person.save(update_fields=fields)
    return person


def attach(row, *, create=True):
    """Point a row at its person (or at nobody) and save the link. Returns the person.

    Called whenever a row's number, email or name changes — that is the whole maintenance
    story: no mapping screen, no suggestions, no merge."""
    try:
        person = person_for(row, create=create)
    except Conflict:
        person = None
    if row.app_user_id != (person.id if person else None):
        type(row).objects.filter(pk=row.pk).update(app_user=person)
        row.app_user = person
    return person


def detach_unused(person):
    """Delete a person nothing points at any more — unless they have a login, which is
    somebody's app access and goes only when the console says so."""
    if person is None or person.has_login:
        return False
    if person.customers.exists() or person.employees.exists():
        return False
    person.delete()
    return True


@transaction.atomic
def rebuild(rows):
    """Re-point a batch of rows — used by the audit command and after a bulk change."""
    touched = set()
    for row in rows:
        before = row.app_user
        attach(row)
        if before and before.id != (row.app_user_id or 0):
            touched.add(before)
    for person in touched:
        detach_unused(person)
    return len(rows)
