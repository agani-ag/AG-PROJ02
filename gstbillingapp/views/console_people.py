"""Console: looking at the people who use the app. Nothing here changes anything.

There is nothing to issue and nothing to map. A customer row carrying a mobile number IS a
person (identity.py), their app login opens by itself, and their password starts as that same
number. So the console's whole job is to show what that produced:

  * **All customers** — one line per person, and the businesses they reach;
  * **Business customers** — every customer row, business by business, and who it belongs to;
  * **One person** — their ledgers, their postings, the state of their login;
  * **To look at** — the rows a number can't speak for (identity_audit.py).

Every action that used to live here — issue, reset, deactivate, map, merge, ungroup — is gone.
"""
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, render

from .. import appusers, identity_audit
from ..console_auth import console_required
from ..models import AppUser, Book, Customer, EmployeePosting


def _brand(user):
    profile = getattr(user, "userprofile", None)
    return ((profile.business_brand or profile.business_title) if profile else "") or user.username


def _rows_for(people):
    """One pass for the list: each person's businesses, ledgers and what they owe."""
    ids = [p.id for p in people]
    customers, posts, owed = {}, {}, {}
    for c in (Customer.objects.filter(app_user_id__in=ids)
              .select_related("user", "user__userprofile")):
        customers.setdefault(c.app_user_id, []).append(c)
    for p in (EmployeePosting.objects.filter(employee__app_user_id__in=ids, is_active=True)
              .select_related("business", "business__userprofile", "employee")):
        posts.setdefault(p.employee.app_user_id, []).append(p)
    for pid, balance in Book.objects.filter(
            customer__app_user_id__in=ids).values_list("customer__app_user_id", "current_balance"):
        owed[pid] = owed.get(pid, 0.0) + min(float(balance or 0), 0.0)
    out = []
    for person in people:
        rows = customers.get(person.id, [])
        postings = posts.get(person.id, [])
        out.append({
            "person": person, "rows": rows, "postings": postings,
            "brands": sorted({_brand(c.user) for c in rows if c.user_id}
                             | {_brand(p.business) for p in postings}),
            "visible": sum(1 for c in rows if appusers.row_is_visible(c)),
            "owed": round(-owed.get(person.id, 0.0), 2),
        })
    return out


def _people_page(request, *, staff_side):
    q = (request.GET.get("q") or "").strip()
    people = appusers.find_people(q)
    people = (people.filter(employees__isnull=False) if staff_side
              else people.filter(customers__isnull=False)).distinct()
    rows = _rows_for(list(people.order_by("name", "id")[:300]))
    problems = identity_audit.summary()
    return render(request, "console/people.html", {
        "rows": rows, "q": q, "staff_side": staff_side,
        "title": "Employees" if staff_side else "Customers",
        "count_all": len(rows),
        "count_login": sum(1 for r in rows if r["person"].login_status == AppUser.LOGIN_ACTIVE
                           and r["person"].connection != "not_enabled"),
        "count_waiting": sum(1 for r in rows if r["person"].connection == "not_enabled"),
        "count_shared": sum(1 for r in rows if len(r["brands"]) > 1),
        "problem_count": (problems["counts"]["unusable"] + problems["counts"]["duplicates"]
                          + len(problems["conflicts"]) + len(problems["own_contact"])),
    })


@console_required
def customers(request):
    """Everyone who has a ledger somewhere — the combined view, one line per person."""
    return _people_page(request, staff_side=False)


@console_required
def employees(request):
    """Everyone who works for a business."""
    return _people_page(request, staff_side=True)


@console_required
def rows(request):
    """Every customer row, business by business — the same people seen the other way round."""
    q = (request.GET.get("q") or "").strip()
    biz = request.GET.get("biz")
    qs = (Customer.objects.select_related("user", "user__userprofile", "app_user")
          .order_by("user_id", "customer_name", "id"))
    if biz and biz.isdigit():
        qs = qs.filter(user_id=int(biz))
    if q:
        qs = qs.filter(customer_name__icontains=q) | qs.filter(customer_phone__icontains=q)
    rows = [{"row": c, "brand": _brand(c.user) if c.user_id else "—",
             "person": c.app_user, "visible": appusers.row_is_visible(c),
             "shared": c.app_user and c.app_user.customers.exclude(user_id=c.user_id).exists()}
            for c in qs.distinct()[:500]]
    return render(request, "console/customer_rows.html", {
        "rows": rows, "q": q, "biz": int(biz) if biz and biz.isdigit() else None,
        "businesses": User.objects.select_related("userprofile").order_by("id"),
        "shared_count": sum(1 for r in rows if r["shared"]),
    })


@console_required
def person(request, person_id):
    """One person: who they are, what they reach, and the state of their login."""
    row = get_object_or_404(AppUser, id=person_id)
    detail = _rows_for([row])[0]
    return render(request, "console/person.html", {
        **detail,
        "blockers": appusers.login_blockers(row),
        "rows_seen": appusers.customer_rows(row),
        "visible_rows": appusers.visible_rows(row),
    })


@console_required
def problems(request):
    """The rows a number can't speak for — fixed by the business on its own customer screen."""
    return render(request, "console/problems.html", identity_audit.summary())
