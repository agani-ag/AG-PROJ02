"""Shared customers: one real shop owner (a Party) across the businesses that sell to them.

The rules (see md/SHARED_CUSTOMERS_PLAN.md):

  * Only a platform admin creates or changes a Party. Nothing here maps a customer row on
    its own — rows sharing a phone number or a valid GSTIN are offered as suggestions, and
    that is all.
  * A customer row belongs to at most one Party.
  * A business's ledger shows in the owner's app only when all three hold: the row is
    mapped, the business has the customer app switched on, and the business has that
    customer's mobile toggle on.
  * The owner's single app login lives on the Party. SyncUp stores the password and does
    the login; GSTSync issues it, resets it, and keeps SyncUp's is_active in step.
"""
import logging
from collections import defaultdict

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import syncup_client
from .gstin import is_valid_gstin, normalise_gstin
from .models import Book, Customer, Party, PartyMapping, UserProfile
from .passwords import generate_customer_password

log = logging.getLogger(__name__)


class LoginBlocked(Exception):
    """A login can't be issued. `reasons` holds the human-readable causes."""

    def __init__(self, reasons):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def normalise_phone(value):
    """The last 10 digits, so +91 98765 43210 and 9876543210 compare equal. "" if fewer."""
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else ""


def mapping_of(customer):
    """The row's PartyMapping, or None."""
    try:
        return customer.party_mapping
    except PartyMapping.DoesNotExist:
        return None


def party_for(customer):
    m = mapping_of(customer)
    return m.party if m else None


def members(party):
    """Every customer row mapped to this Party, whatever its visibility."""
    return list(Customer.objects.filter(party_mapping__party=party)
                .select_related("user", "user__userprofile").order_by("user_id", "id"))


def _profile(customer):
    return getattr(customer.user, "userprofile", None) if customer.user_id else None


def app_enabled(user):
    """The business's customer-app switch. A business with no profile yet takes the
    field's default (on)."""
    profile = getattr(user, "userprofile", None)
    return True if profile is None else profile.customer_app_enabled


def row_is_visible(customer):
    """Does this row's ledger show in the customer app? Needs the business's customer-app
    switch and the row's own mobile toggle."""
    return bool(customer.user_id and customer.is_mobile_user and app_enabled(customer.user))


def visible_rows(party):
    return [c for c in members(party) if row_is_visible(c)]


def own_business_gstins():
    """GSTINs of our own businesses — a customer row carrying one is inter-company."""
    return {normalise_gstin(g) for g in UserProfile.objects
            .exclude(business_gst__isnull=True).exclude(business_gst="")
            .values_list("business_gst", flat=True)}


def is_inter_company(customer, own=None):
    own = own_business_gstins() if own is None else own
    g = normalise_gstin(customer.customer_gst)
    return bool(g) and g in own


def evidence_keys(customer):
    """What may suggest this row is the same owner as another: its phone, and its GSTIN
    only when the GSTIN is valid (a typo or placeholder proves nothing)."""
    keys = []
    phone = normalise_phone(customer.customer_phone)
    if phone:
        keys.append(("phone", phone))
    if is_valid_gstin(customer.customer_gst):
        keys.append(("gstin", normalise_gstin(customer.customer_gst)))
    return keys


def evidence_between(customers):
    """How a set of rows is linked: 'phone_gstin', 'phone', 'gstin', or 'manual' when they
    share nothing. Recorded on each mapping so the decision can be explained later."""
    seen = defaultdict(int)
    for c in customers:
        for key in set(evidence_keys(c)):
            seen[key] += 1
    shared = {kind for (kind, _), n in seen.items() if n > 1}
    if {"phone", "gstin"} <= shared:
        return "phone_gstin"
    if shared:
        return shared.pop()
    return "manual"


def describe_rows(customers):
    """Side-by-side facts for the console: business, balance, current Party, visibility."""
    ids = [c.id for c in customers]
    balances = dict(Book.objects.filter(customer_id__in=ids)
                    .values_list("customer_id", "current_balance"))
    own = own_business_gstins()
    out = []
    for c in customers:
        profile = _profile(c)
        mapping = mapping_of(c)
        balance = float(balances.get(c.id) or 0)
        out.append({
            "customer": c,
            "business": c.user,
            "brand": ((profile.business_brand or profile.business_title) if profile
                      else (c.user.username if c.user_id else "—")),
            "gstin_valid": is_valid_gstin(c.customer_gst),
            "owed": -balance if balance < 0 else 0.0,
            "advance": balance if balance > 0 else 0.0,
            "party": mapping.party if mapping else None,
            "app_enabled": bool(profile and profile.customer_app_enabled),
            "visible": row_is_visible(c),
            "inter_company": is_inter_company(c, own),
        })
    return out


def map_warnings(customers):
    """Things the admin should look at before saving a mapping. Warnings, never blocks."""
    warnings = []
    if len(customers) > 1 and evidence_between(customers) == "manual":
        warnings.append("These rows share no phone number or GSTIN. Check they really are "
                        "the same shop owner.")
    own = own_business_gstins()
    for c in customers:
        profile = _profile(c)
        label = (profile.business_brand or profile.business_title) if profile else "A business"
        if is_inter_company(c, own):
            warnings.append("%s's row is one of your own businesses. It can be grouped, but it "
                            "never gets an app login." % label)
        elif profile and not profile.customer_app_enabled:
            warnings.append("%s doesn't have the customer app switched on, so its ledger won't "
                            "show in the app." % label)
    per_business = defaultdict(list)
    for c in customers:
        per_business[c.user_id].append(c)
    for same in per_business.values():
        if len(same) > 1:
            profile = _profile(same[0])
            label = ((profile.business_brand or profile.business_title) if profile
                     else None) or "one business"
            warnings.append("%d rows are at %s. If it's the same shop entered twice, %s should "
                            "combine them into one; if they're separate shops, both show in the "
                            "app as separate accounts." % (len(same), label, label))
    gstins = {normalise_gstin(c.customer_gst) for c in customers if is_valid_gstin(c.customer_gst)}
    if len(gstins) > 1:
        warnings.append("These rows carry %d different GSTINs. That's fine for one owner with "
                        "several firms." % len(gstins))
    return warnings


# --------------------------------------------------------------------------- #
# Suggestions
# --------------------------------------------------------------------------- #
def suggestion_groups():
    """Rows that look like one shop owner and haven't been settled by an admin yet.

    Rows are joined when they share a phone number or a valid GSTIN — chained, so A–B by
    phone and B–C by GSTIN form one group. A group is offered only when it spans at least
    two businesses and isn't already a single Party. Rows already mapped stay in the group
    (shown with their Party) so the admin can add the rest to it, or merge.
    """
    rows = list(Customer.objects.exclude(user__isnull=True)
                .select_related("user", "user__userprofile", "party_mapping__party"))
    parent = {c.id: c.id for c in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    first = {}
    for c in rows:
        for key in evidence_keys(c):
            if key in first:
                a, b = find(first[key]), find(c.id)
                if a != b:
                    parent[a] = b
            else:
                first[key] = c.id

    components = defaultdict(list)
    for c in rows:
        components[find(c.id)].append(c)

    groups = []
    for comp in components.values():
        if len({c.user_id for c in comp}) < 2:
            continue
        mappings = [mapping_of(c) for c in comp]
        party_ids = {m.party_id for m in mappings if m}
        if all(mappings) and len(party_ids) == 1:
            continue                                   # already settled
        comp.sort(key=lambda c: (c.user_id, c.id))
        groups.append({
            "key": min(c.id for c in comp),
            "rows": comp,
            "evidence": evidence_between(comp),
            "parties": sorted({m.party for m in mappings if m}, key=lambda p: p.id),
            "unmapped": sum(1 for m in mappings if not m),
            "name": _likely_name(comp),
        })
    groups.sort(key=lambda g: (-len({c.user_id for c in g["rows"]}), g["name"]))
    return groups


def suggestion_group(key):
    for group in suggestion_groups():
        if group["key"] == key:
            return group
    return None


def _likely_name(customers):
    counts = defaultdict(int)
    for c in customers:
        counts[(c.customer_name or "").strip()] += 1
    return max(counts.items(), key=lambda kv: (kv[1], len(kv[0])))[0] if counts else ""


# --------------------------------------------------------------------------- #
# Mapping (admin actions)
# --------------------------------------------------------------------------- #
@transaction.atomic
def _map_rows(party, customers, admin, note):
    evidence = evidence_between(list(customers) + members(party))
    touched = {party.id}
    for c in customers:
        m = mapping_of(c)
        if m and m.party_id == party.id:
            continue
        if m:                                          # the admin chose to move it
            touched.add(m.party_id)
            m.party, m.evidence, m.note, m.mapped_by = party, evidence, note, admin
            m.save()
        else:
            PartyMapping.objects.create(party=party, customer=c, evidence=evidence,
                                        note=note, mapped_by=admin)
    return touched


def create_party(*, name, customers, admin=None, note=""):
    customers = list(customers)
    if not customers:
        raise ValueError("Pick at least one customer row.")
    with transaction.atomic():
        party = Party.objects.create(name=(name or "").strip()[:200] or
                                     customers[0].customer_name, created_by=admin)
        touched = _map_rows(party, customers, admin, note)
    refresh_parties(touched)
    return party


def add_rows(party, customers, *, admin=None, note=""):
    customers = list(customers)
    if customers:
        refresh_parties(_map_rows(party, customers, admin, note))


def remove_row(customer):
    """Take a row out of its Party. Its ledger leaves the owner's app on their next load."""
    m = mapping_of(customer)
    if m is None:
        return None
    party = m.party
    m.delete()
    refresh_login(party)
    return party


def merge_parties(survivor, other):
    """Move every row of `other` into `survivor`, then delete `other`.

    `other`'s app login is switched off in SyncUp first. If that fails nothing is changed
    and SyncUpError propagates, so a login can't be left behind for a Party that's gone."""
    if survivor.pk == other.pk:
        raise ValueError("Pick a different customer to merge into.")
    if other.login_status == Party.LOGIN_ACTIVE:
        syncup_client.set_account_active(other.external_id, False)
    with transaction.atomic():
        PartyMapping.objects.filter(party=other).update(party=survivor)
        if other.notes and not survivor.notes:
            survivor.notes = other.notes
            survivor.save(update_fields=["notes"])
        other.delete()
    refresh_login(survivor)
    return survivor


def delete_party(party):
    """Ungroup a Party entirely. Its rows stay with their businesses, unmapped."""
    if party.login_status == Party.LOGIN_ACTIVE:
        syncup_client.set_account_active(party.external_id, False)
    party.delete()


def copy_location(party, source, *, include_day=False):
    """Copy map position and place (optionally collection day) from one of the owner's rows
    to their other rows. Replaces the old business-side location mapper, which wrote across
    every business on the platform with no login."""
    fields = ["customer_latitude", "customer_longitude", "customer_place"]
    if include_day:
        fields.append("collection_day")
    targets = [c for c in members(party) if c.id != source.id]
    for c in targets:
        for f in fields:
            setattr(c, f, getattr(source, f))
    if targets:
        Customer.objects.bulk_update(targets, fields)
    return len(targets)


# --------------------------------------------------------------------------- #
# The owner's app login (SyncUp)
# --------------------------------------------------------------------------- #
def app_link_prefix():
    return syncup_client.link_base() + "/m/customer/"


def app_link(party):
    from .mobile_auth import mint_party_token      # mobile_auth imports this module
    return app_link_prefix() + "?t=" + mint_party_token(party)


def login_blockers(party):
    """Why a login can't be issued right now — empty when it can."""
    reasons = []
    cfg = syncup_client.config()
    if not cfg.is_configured:
        reasons.append("SyncUp isn't set up yet \u2014 add its address and partner key under "
                       "Settings.")
    if not syncup_client.link_base(cfg):
        reasons.append("Set this site's public https:// address under Settings \u2014 the app "
                       "link is built from it.")
    rows = members(party)
    if not rows:
        reasons.append("No customer rows are mapped to this customer yet.")
    own = own_business_gstins()
    if any(is_inter_company(c, own) for c in rows):
        reasons.append("This is one of your own businesses, so it doesn't get an app login.")
    elif rows and not any(row_is_visible(c) for c in rows):
        reasons.append("None of their businesses shows them in the app yet. A business needs "
                       "the customer app switched on and this customer's Mobile toggle on.")
    return reasons


def _record_sync(party, active):
    party.syncup_active = active
    party.syncup_synced_at = timezone.now()
    party.syncup_error = ""


def issue_login(party):
    """Create the owner's login, or re-create it. Returns the new password — the only time
    it exists outside SyncUp, so the caller shows it once and never stores it.

    Re-issuing also bumps the link token, so a link from an earlier issue stops working."""
    blockers = login_blockers(party)
    if blockers:
        raise LoginBlocked(blockers)
    password = generate_customer_password()
    party.token_version += 1
    # One call: the account and its app link together (SyncUp replaces the link by key).
    syncup_client.upsert_account(party.external_id, name=party.name, email=party.login_email,
                                 password=password, is_active=True, app_link=app_link(party))
    party.login_status = Party.LOGIN_ACTIVE
    party.login_issued_at = timezone.now()
    party.tile_text = ""            # the new link has no "₹… due" subtitle yet
    _record_sync(party, True)
    party.save()
    return password


def reset_password(party):
    """A new password for an active login, shown once. The link keeps working."""
    if party.login_status != Party.LOGIN_ACTIVE:
        raise LoginBlocked(["This customer has no active login to reset."])
    password = generate_customer_password()
    active = bool(visible_rows(party))
    syncup_client.upsert_account(party.external_id, name=party.name, email=party.login_email,
                                 password=password, is_active=active)
    _record_sync(party, active)
    party.save(update_fields=["syncup_active", "syncup_synced_at", "syncup_error"])
    return password


def deactivate_login(party):
    """Switch the login off. Takes effect in GSTSync immediately — the link token is bumped
    before SyncUp is asked — so the /m/ link dies even while SyncUp is unreachable. Returns
    False (with the error recorded for a retry) if SyncUp couldn't be told."""
    party.login_status = Party.LOGIN_INACTIVE
    party.token_version += 1
    party.save(update_fields=["login_status", "token_version"])
    try:
        syncup_client.set_account_active(party.external_id, False)
    except syncup_client.SyncUpError as e:
        Party.objects.filter(pk=party.pk).update(syncup_error=str(e)[:300])
        return False
    _record_sync(party, False)
    party.save(update_fields=["syncup_active", "syncup_synced_at", "syncup_error"])
    return True


def refresh_login(party):
    """Keep SyncUp's is_active equal to 'admin says active AND at least one visible ledger'.

    Called after anything that can change visibility: a mapping, a business's mobile toggle,
    a business's customer-app switch. Makes no call when nothing changed, and NEVER raises —
    a business toggling a customer must not fail or wait long because SyncUp is down: the
    push is capped at QUICK_TIMEOUT, and a failure is recorded on the Party and retried by
    /cron/syncup (or the console's Retry sync).

    Returns "unchanged", "pushed" or "failed" (None when there's no login to sync)."""
    party = Party.objects.filter(pk=party.pk).first()
    if party is None or party.login_status == Party.LOGIN_NONE:
        return None
    want = party.login_status == Party.LOGIN_ACTIVE and bool(visible_rows(party))
    if party.syncup_active == want and not party.syncup_error:
        return "unchanged"
    try:
        syncup_client.set_account_active(party.external_id, want,
                                         timeout=syncup_client.QUICK_TIMEOUT)
    except syncup_client.SyncUpError as e:
        log.warning("SyncUp is_active push failed for %s: %s", party.external_id, e)
        Party.objects.filter(pk=party.pk).update(syncup_error=str(e)[:300])
        return "failed"
    Party.objects.filter(pk=party.pk).update(syncup_active=want, syncup_error="",
                                             syncup_synced_at=timezone.now())
    return "pushed"


def retry_pending():
    """Bring every customer login's SyncUp state up to date — for /cron/syncup. Logins
    already in step cost no call. Returns counts by outcome."""
    counts = {"pushed": 0, "failed": 0, "unchanged": 0}
    for party in Party.objects.exclude(login_status=Party.LOGIN_NONE):
        outcome = refresh_login(party)
        if outcome:
            counts[outcome] += 1
    return counts


def refresh_parties(party_ids):
    for party in Party.objects.filter(id__in=list(party_ids)):
        refresh_login(party)


def refresh_for_customer(customer):
    party = party_for(customer)
    if party is not None:
        refresh_login(party)


def refresh_for_business(user):
    """After a business's customer-app switch changes: every Party with a row there."""
    refresh_parties(Party.objects.filter(mappings__customer__user=user)
                    .values_list("id", flat=True).distinct())


# --------------------------------------------------------------------------- #
# Finding rows for the console
# --------------------------------------------------------------------------- #
def rows_sharing_evidence(customers):
    """Other customer rows sharing a phone or valid GSTIN with any of `customers`.

    This is how a suggestion resurfaces: a business later adds a GSTIN or phone that
    matches a Party member, and the row shows on that Party's page as "may belong here".
    It is never added by itself."""
    customers = list(customers)
    keys = {k for c in customers for k in evidence_keys(c)}
    if not keys:
        return []
    own = {c.id for c in customers}
    return [c for c in Customer.objects.exclude(user__isnull=True).exclude(id__in=own)
            .select_related("user", "user__userprofile", "party_mapping__party")
            .order_by("user_id", "id")
            if keys & set(evidence_keys(c))]


def search_rows(q, *, exclude_party=None, limit=25):
    """Customer rows from every business matching a name, phone or GSTIN fragment."""
    qs = (Customer.objects.exclude(user__isnull=True)
          .filter(Q(customer_name__icontains=q) | Q(customer_phone__icontains=q)
                  | Q(customer_gst__icontains=q))
          .select_related("user", "user__userprofile", "party_mapping__party")
          .order_by("customer_name", "id"))
    if exclude_party is not None:
        qs = qs.exclude(party_mapping__party=exclude_party)
    return list(qs[:limit])


# --------------------------------------------------------------------------- #
# Bulk (console)
# --------------------------------------------------------------------------- #
def bulk_skip_reason(group, own=None):
    """Why a suggestion needs a one-by-one review rather than bulk mapping — "" when it
    doesn't. Bulk is only for the clear case: one owner's rows at different businesses,
    joining at most one existing customer. Everything else is left for a human look."""
    rows = group["rows"]
    if len(group["parties"]) > 1:
        return "its rows already belong to different customers"
    if len({c.user_id for c in rows}) < len(rows):
        return "two of its rows are at the same business"
    own = own_business_gstins() if own is None else own
    if any(is_inter_company(c, own) for c in rows):
        return "one row is one of your own businesses"
    return ""


def bulk_map(keys, admin=None):
    """Map the ticked suggestions in one go. Each becomes a customer, or joins the one
    customer it already touches; suggestions that need a closer look are skipped and
    reported, never guessed at. Returns {"created", "added", "skipped": [(name, reason)]}."""
    wanted = set(keys)
    own = own_business_gstins()
    result = {"created": 0, "added": 0, "skipped": []}
    for group in suggestion_groups():
        if group["key"] not in wanted:
            continue
        reason = bulk_skip_reason(group, own)
        if reason:
            result["skipped"].append((group["name"], reason))
            continue
        if group["parties"]:
            unmapped = [c for c in group["rows"] if mapping_of(c) is None]
            add_rows(group["parties"][0], unmapped, admin=admin, note="Bulk review")
            result["added"] += 1
        else:
            create_party(name=group["name"], customers=group["rows"], admin=admin,
                         note="Bulk review")
            result["created"] += 1
    return result


def ready_to_issue(party):
    """Can a login be issued for this customer right now: none active, nothing blocking."""
    return party.login_status != Party.LOGIN_ACTIVE and not login_blockers(party)
