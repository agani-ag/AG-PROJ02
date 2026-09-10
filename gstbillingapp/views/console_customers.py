"""Console: shared customers — suggestions, Parties, and each Party's customer-app login.

Every decision that customer rows are one shop owner is made on these screens, by a platform
admin. Nothing here maps a row by itself; the rules live in parties.py. A business never
sees any of this: it keeps its own customer rows and its own Mobile toggle, nothing more.
"""
from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .. import parties
from ..console_auth import console_required
from ..models import Book, Customer, Party, PartyMapping, SyncUpSettings
from ..syncup_client import SyncUpError, link_base, upsert_account


def _posted_ids(request, name="customer_ids"):
    return [int(v) for v in request.POST.getlist(name) if v.strip().isdigit()]


def _note(request):
    return (request.POST.get("note") or "").strip()[:200]


def _plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def _back(party):
    return redirect("console_party", party_id=party.id)


def _party_rows(party_list):
    """List facts for each Party in a fixed number of queries: brands, rows, amount owed."""
    ids = [p.id for p in party_list]
    domain = SyncUpSettings.load().login_domain
    by_party = {pid: [] for pid in ids}
    for m in (PartyMapping.objects.filter(party_id__in=ids)
              .select_related("customer__user__userprofile")):
        by_party[m.party_id].append(m.customer)
    balances = dict(Book.objects.filter(customer_id__in=[c.id for rows in by_party.values()
                                                         for c in rows])
                    .values_list("customer_id", "current_balance"))
    out = []
    for p in party_list:
        rows = by_party[p.id]
        brands = []
        for c in rows:
            prof = getattr(c.user, "userprofile", None) if c.user_id else None
            name = ((prof.business_brand or prof.business_title) if prof else None) or (
                c.user.username if c.user_id else "—")
            if name not in brands:
                brands.append(name)
        owed = sum(-float(balances.get(c.id) or 0) for c in rows
                   if float(balances.get(c.id) or 0) < 0)
        out.append({"party": p, "rows": len(rows), "brands": brands, "owed": owed,
                    "email": p.login_email_at(domain),
                    "visible": sum(1 for c in rows if parties.row_is_visible(c))})
    return out


# --------------------------------------------------------------------------- #
# List
# --------------------------------------------------------------------------- #
@console_required
def customers(request):
    """Mapped Parties, unreviewed suggestions, and every row nobody has mapped yet."""
    q = (request.GET.get("q") or "").strip()
    show = request.GET.get("show") or "mapped"
    if show not in ("mapped", "suggestions", "unmapped"):
        show = "mapped"

    party_qs = Party.objects.all()
    unmapped_qs = (Customer.objects.exclude(user__isnull=True).filter(party_mapping__isnull=True)
                   .select_related("user", "user__userprofile").order_by("customer_name", "id"))
    groups = parties.suggestion_groups()
    if q:
        party_qs = party_qs.filter(
            Q(name__icontains=q) | Q(mappings__customer__customer_name__icontains=q)
            | Q(mappings__customer__customer_phone__icontains=q)
            | Q(mappings__customer__customer_gst__icontains=q)).distinct()
        unmapped_qs = unmapped_qs.filter(
            Q(customer_name__icontains=q) | Q(customer_phone__icontains=q)
            | Q(customer_gst__icontains=q))
        ql = q.lower()
        groups = [g for g in groups if any(
            ql in (v or "").lower() for c in g["rows"]
            for v in (c.customer_name, c.customer_phone, c.customer_gst))]

    ctx = {
        "q": q, "show": show,
        "count_mapped": party_qs.count(),
        "count_suggestions": len(groups),
        "count_unmapped": unmapped_qs.count(),
        "count_logins": party_qs.filter(login_status=Party.LOGIN_ACTIVE).count(),
    }
    if show == "mapped":
        ctx["party_rows"] = _party_rows(list(party_qs.order_by("name", "id")))
    elif show == "suggestions":
        ctx["groups"] = groups
    else:
        page_obj = Paginator(unmapped_qs, 50).get_page(request.GET.get("page"))
        ctx.update(page_obj=page_obj, total_count=page_obj.paginator.count,
                   rows=parties.describe_rows(list(page_obj)),
                   querystring=urlencode({"show": show, "q": q} if q else {"show": show}))
    return render(request, "console/customers.html", ctx)


# --------------------------------------------------------------------------- #
# Suggestions and unmapped rows
# --------------------------------------------------------------------------- #
@console_required
def suggestion(request, key):
    """Review one suggestion: rows that share a phone or valid GSTIN, side by side. The
    admin ticks the rows that really are one owner and saves them as a Party."""
    group = parties.suggestion_group(key)
    if group is None:
        messages.success(request, "That suggestion has already been settled.")
        return redirect(reverse("console_customers") + "?show=suggestions")

    if request.method == "POST":
        wanted = set(_posted_ids(request))
        chosen = [c for c in group["rows"] if c.id in wanted]
        if not chosen:
            messages.error(request, "Tick at least one row.")
            return redirect("console_suggestion", key=key)
        target = (request.POST.get("party_id") or "").strip()
        if target.isdigit():
            party = next((p for p in group["parties"] if p.id == int(target)), None)
            if party is None:
                raise Http404("Not a Party in this suggestion.")
            parties.add_rows(party, chosen, admin=request.platform_admin, note=_note(request))
            messages.success(request, "Added %s to %s." % (_plural(len(chosen), "row"), party.name))
        else:
            party = parties.create_party(name=request.POST.get("name"), customers=chosen,
                                         admin=request.platform_admin, note=_note(request))
            messages.success(request, "Mapped %s as %s." % (_plural(len(chosen), "row"), party.name))
        return _back(party)

    return render(request, "console/suggestion.html", {
        "group": group,
        "rows": parties.describe_rows(group["rows"]),
        "warnings": parties.map_warnings(group["rows"]),
    })


@console_required
def customer_detail(request, customer_id):
    """One customer row. A mapped row opens its Party; an unmapped one can start a Party
    or join an existing one."""
    customer = get_object_or_404(Customer.objects.select_related("user", "user__userprofile"),
                                 id=customer_id)
    party = parties.party_for(customer)
    if party is not None:
        return _back(party)
    related = parties.rows_sharing_evidence([customer])
    near = sorted({parties.party_for(c) for c in related} - {None}, key=lambda p: p.id)
    pq = (request.GET.get("pq") or "").strip()
    return render(request, "console/customer_detail.html", {
        "customer": customer,
        "row": parties.describe_rows([customer])[0],
        "related": parties.describe_rows(related),
        "near": near,
        "group": next((g for g in parties.suggestion_groups() if customer in g["rows"]), None),
        "pq": pq,
        "found": list(Party.objects.filter(name__icontains=pq)[:20]) if pq else [],
    })


@console_required
@require_POST
def party_new(request):
    rows = list(Customer.objects.filter(id__in=_posted_ids(request))
                .exclude(user__isnull=True).exclude(party_mapping__isnull=False))
    if not rows:
        messages.error(request, "Pick at least one unmapped customer row.")
        return redirect("console_customers")
    party = parties.create_party(name=request.POST.get("name"), customers=rows,
                                 admin=request.platform_admin, note=_note(request))
    messages.success(request, "Created %s." % party.name)
    return _back(party)


# --------------------------------------------------------------------------- #
# Party page
# --------------------------------------------------------------------------- #
@console_required
def party_detail(request, party_id):
    party = get_object_or_404(Party, id=party_id)
    rows = parties.members(party)
    described = parties.describe_rows(rows)
    aq = (request.GET.get("aq") or "").strip()
    return render(request, "console/party_detail.html", {
        "party": party,
        "rows": described,
        "owed": sum(r["owed"] for r in described),
        "business_count": len({c.user_id for c in rows}),
        "visible_count": sum(1 for r in described if r["visible"]),
        "maybe": parties.describe_rows(parties.rows_sharing_evidence(rows)),
        "aq": aq,
        "found": parties.describe_rows(parties.search_rows(aq, exclude_party=party)) if aq else [],
        "others": Party.objects.exclude(id=party.id).order_by("name", "id"),
        "blockers": parties.login_blockers(party),
        "syncup_ready": bool(SyncUpSettings.load().is_configured and link_base()),
        "warnings": parties.map_warnings(rows),
    })


@console_required
@require_POST
def party_update(request, party_id):
    party = get_object_or_404(Party, id=party_id)
    name = (request.POST.get("name") or "").strip()[:200]
    if not name:
        messages.error(request, "Name is required.")
        return _back(party)
    party.name = name
    party.notes = (request.POST.get("notes") or "").strip() or None
    party.save(update_fields=["name", "notes"])
    if party.has_login:
        # SyncUp shows this name in the app; keep it in step, but a failure only warns.
        try:
            upsert_account(party.external_id, name=party.name, email=party.login_email,
                           is_active=bool(party.syncup_active))
        except SyncUpError as e:
            messages.error(request, "Saved here, but SyncUp still has the old name: %s" % e)
            return _back(party)
    messages.success(request, "Saved.")
    return _back(party)


@console_required
@require_POST
def party_add(request, party_id):
    party = get_object_or_404(Party, id=party_id)
    rows = list(Customer.objects.filter(id__in=_posted_ids(request)).exclude(user__isnull=True))
    if not rows:
        messages.error(request, "Tick at least one row to add.")
        return _back(party)
    moved = [c for c in rows if (m := parties.mapping_of(c)) and m.party_id != party.id]
    parties.add_rows(party, rows, admin=request.platform_admin, note=_note(request))
    msg = "Added %s." % _plural(len(rows), "row")
    if moved:
        msg += " %s moved here from another customer." % _plural(len(moved), "row")
    messages.success(request, msg)
    return _back(party)


@console_required
@require_POST
def party_remove(request, party_id):
    party = get_object_or_404(Party, id=party_id)
    customer = get_object_or_404(Customer, id=request.POST.get("customer_id") or 0,
                                 party_mapping__party=party)
    parties.remove_row(customer)
    messages.success(request, "Removed %s's row. It no longer shows in their app." %
                     (customer.user.username if customer.user_id else "the"))
    return _back(party)


@console_required
@require_POST
def party_merge(request, party_id):
    """Merge another Party into this one. This one survives; the other's login is switched
    off first, and nothing changes if SyncUp can't be told."""
    party = get_object_or_404(Party, id=party_id)
    other = get_object_or_404(Party, id=request.POST.get("other_id") or 0)
    if other.id == party.id:
        messages.error(request, "Pick a different customer to merge.")
        return _back(party)
    name = other.name
    try:
        parties.merge_parties(party, other)
    except SyncUpError as e:
        messages.error(request, "Couldn't switch off %s's login in SyncUp, so nothing was "
                                "merged: %s" % (name, e))
        return _back(party)
    messages.success(request, "Merged %s into %s." % (name, party.name))
    return _back(party)


@console_required
@require_POST
def party_copy_location(request, party_id):
    party = get_object_or_404(Party, id=party_id)
    source = get_object_or_404(Customer, id=request.POST.get("source_id") or 0,
                               party_mapping__party=party)
    n = parties.copy_location(party, source, include_day=bool(request.POST.get("include_day")))
    messages.success(request, "Copied the location to %s." % _plural(n, "other row"))
    return _back(party)


@console_required
@require_POST
def party_delete(request, party_id):
    """Ungroup: the Party goes, its rows stay with their businesses, unmapped."""
    party = get_object_or_404(Party, id=party_id)
    name = party.name
    try:
        parties.delete_party(party)
    except SyncUpError as e:
        messages.error(request, "Couldn't switch off the login in SyncUp, so nothing was "
                                "changed: %s" % e)
        return _back(party)
    messages.success(request, "Ungrouped %s. Its rows are unmapped again." % name)
    return redirect("console_customers")


# --------------------------------------------------------------------------- #
# Customer-app login (SyncUp)
# --------------------------------------------------------------------------- #
def _password_page(request, party, password, issued):
    """The one and only time this password is shown. It's rendered straight into this
    response — never stored, never put in the session or a redirect — and never_cache on
    the views keeps the page out of the browser cache."""
    return render(request, "console/party_password.html",
                  {"party": party, "password": password, "issued": issued})


@never_cache
@console_required
@require_POST
def party_login_issue(request, party_id):
    party = get_object_or_404(Party, id=party_id)
    try:
        password = parties.issue_login(party)
    except parties.LoginBlocked as e:
        for reason in e.reasons:
            messages.error(request, reason)
        return _back(party)
    except SyncUpError as e:
        messages.error(request, "SyncUp didn't accept the login: %s" % e)
        return _back(party)
    return _password_page(request, party, password, issued=True)


@never_cache
@console_required
@require_POST
def party_login_reset(request, party_id):
    party = get_object_or_404(Party, id=party_id)
    try:
        password = parties.reset_password(party)
    except parties.LoginBlocked as e:
        for reason in e.reasons:
            messages.error(request, reason)
        return _back(party)
    except SyncUpError as e:
        messages.error(request, "SyncUp didn't accept the new password: %s" % e)
        return _back(party)
    return _password_page(request, party, password, issued=False)


@console_required
@require_POST
def party_login_deactivate(request, party_id):
    party = get_object_or_404(Party, id=party_id)
    if party.login_status != Party.LOGIN_ACTIVE:
        messages.error(request, "This customer has no active login.")
    elif parties.deactivate_login(party):
        messages.success(request, "Login deactivated. Their app link stopped working.")
    else:
        messages.error(request, "Deactivated here, and the app link stopped working, but "
                                "SyncUp couldn't be told. Use Retry sync.")
    return _back(party)


@console_required
@require_POST
def party_login_sync(request, party_id):
    party = get_object_or_404(Party, id=party_id)
    if not party.has_login:
        messages.error(request, "This customer has no login to sync.")
        return _back(party)
    if party.login_status == Party.LOGIN_INACTIVE and party.syncup_active is not False:
        # A deactivation SyncUp never heard about.
        parties.deactivate_login(party)
    else:
        parties.refresh_login(party)
    party.refresh_from_db()
    if party.syncup_error:
        messages.error(request, "Still out of sync: %s" % party.syncup_error)
    else:
        messages.success(request, "SyncUp is up to date.")
    return _back(party)
