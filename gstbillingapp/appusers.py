"""The app login of one person — issuing it, switching it off, keeping SyncUp in step.

Who a person is comes from identity.py (their mobile, or their email). This module is only
about their SyncUp account: the password shown once, the /m/ link, and the is_active state
that follows what they can actually see.

Nobody issues anything: a customer with a mobile number can open the app, and their password
starts as **that same number** (they can change it in the app). No address is invented for
them, nothing is mailed, and the console only looks on.

Every call here is one Partner API call, and nothing a business does is ever blocked by
SyncUp being down: a failure is recorded on the person and retried by /cron/syncup.
"""
import hashlib
import logging
import secrets

from django.db.models import Q
from django.utils import timezone

from . import identity, syncup_client
from .identity import clean_email, clean_mobile
from .models import AppUser, Customer, Employee, EmployeePosting

log = logging.getLogger(__name__)

# No look-alikes (0/O, 1/l/I): these are read off a screen and typed on a phone.
_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"


class LoginBlocked(Exception):
    """Why a login can't be issued right now. `reasons` is a list of sentences."""

    def __init__(self, reasons):
        super().__init__(" ".join(reasons))
        self.reasons = reasons


def generate_password(length=10):
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


# --------------------------------------------------------------------------- #
# What a person can see
# --------------------------------------------------------------------------- #
def app_enabled(user):
    """The business's customer-app switch. A business with no profile yet takes the field's
    default (on)."""
    profile = getattr(user, "userprofile", None)
    return True if profile is None else profile.customer_app_enabled


def row_is_visible(customer):
    """Does this row's ledger show in the app? The business's customer-app switch and the
    row's own Mobile toggle, exactly as before."""
    if not customer.user_id or not customer.is_mobile_user:
        return False
    return app_enabled(customer.user)


def customer_rows(person):
    """Every customer row this person holds — one per business that has their number."""
    return list(Customer.objects.filter(app_user=person)
                .select_related("user", "user__userprofile").order_by("user_id", "id"))


def visible_rows(person):
    return [c for c in customer_rows(person) if row_is_visible(c)]


def postings(person):
    """The businesses this person works for — active postings of any employee record of
    theirs, at a business that hasn't switched them off."""
    return list(EmployeePosting.objects.filter(
        employee__app_user=person, is_active=True, employee__is_active=True,
        employee__is_mobile_user=True)
        .select_related("business", "business__userprofile", "employee"))


def is_staff(person):
    return bool(postings(person))


def can_use_app(person):
    """Anything at all to open — a visible ledger or a posting."""
    return bool(visible_rows(person)) or is_staff(person)


# --------------------------------------------------------------------------- #
# The link and the login
# --------------------------------------------------------------------------- #
def app_link_prefix():
    return syncup_client.link_base() + "/m/"


def app_link(person, path=""):
    """A link into the app as this person. `/m/` sends them to whichever side they have;
    `customer/` and `employee/` open one side directly (see views/m/entry.py)."""
    from .mobile_auth import mint_user_token          # mobile_auth imports this module
    return app_link_prefix() + path + "?t=" + mint_user_token(person)


def desired_links(person):
    """The tiles this person should see in SyncUp — one per side they actually have.

    Somebody who buys from one business and works for another is ONE account with the same
    number, so they get two tiles rather than one that has to guess which they meant."""
    links = []
    if visible_rows(person):
        links.append({"external_id": syncup_client.APP_LINK_KEY, "title": "GSTSync",
                      "url": app_link(person, "customer/"), "icon": "home",
                      "description": person.tile_text or None})
    if is_staff(person):
        links.append({"external_id": syncup_client.STAFF_LINK_KEY, "title": "GSTSync Staff",
                      "url": app_link(person, "employee/"), "icon": "briefcase"})
    return links


def prune_links(person, keep):
    """Take away a tile for a side they no longer have — they stopped being staff, or their
    last ledger was hidden. Quiet about failures: the next sync tries again."""
    try:
        for link in syncup_client.list_links(person.external_id):
            key = link.get("external_id") or ""
            if key in (syncup_client.APP_LINK_KEY, syncup_client.STAFF_LINK_KEY) and key not in keep:
                syncup_client.delete_link(link.get("id"))
    except syncup_client.SyncUpError as e:
        log.warning("Tidying tiles for %s failed: %s", person.external_id, e)


def login_blockers(person):
    """Why a login can't be issued right now — empty when it can."""
    reasons = []
    cfg = syncup_client.config()
    if not cfg.is_configured:
        reasons.append("SyncUp isn't set up yet — add its address and partner key under "
                       "Settings.")
    if not syncup_client.link_base(cfg):
        reasons.append("Set this site's public https:// address under Settings — the app link "
                       "is built from it.")
    if not person.mobile and not person.email:
        reasons.append("This person has no mobile number or email, so there is nothing to "
                       "sign in with.")
    if not can_use_app(person):
        reasons.append("They have nothing to open yet: no business shows them a ledger in the "
                       "app, and they have no active posting.")
    return reasons


def _identity_payload(person):
    """What SyncUp is told to recognise them by. Their own number and address — never ours."""
    payload = {}
    if person.mobile:
        payload["phone"] = person.mobile
    if person.email:
        payload["email"] = person.email
    return payload


def identity_signature(person):
    """A fingerprint of exactly what an upsert would tell SyncUp about this person.

    Stored on the person after each successful call, so "have they been told?" is a string
    comparison rather than a question only SyncUp can answer. A digest rather than the
    values themselves: fixed width, and the contact details are already a column away."""
    payload = "%s|%s|%s" % (person.name or person.sign_in, person.mobile, person.email or "")
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:32]


def identity_drifted(person):
    """Does SyncUp hold something other than what we hold? Costs no call."""
    return person.identity_pending or person.identity_sent != identity_signature(person)


def _note_connection(person, user):
    """SyncUp's answer carries the state of OUR connection to this person. A number that
    already belonged to somebody's SyncUp account gives us "not_enabled": the account is
    theirs, and our tiles stay hidden until they switch GSTSync on in the app."""
    status = (user.get("status") or "") if isinstance(user, dict) else ""
    if status and status != person.connection:
        AppUser.objects.filter(pk=person.pk).update(connection=status)
        person.connection = status
    return status


def _record_sync(person, active):
    person.syncup_active = active
    person.syncup_synced_at = timezone.now()
    person.syncup_error = ""


def ensure_login(person):
    """Give them their app login the moment they can use it — nobody has to issue anything.

    The password is **their own mobile number**: there is nothing to hand out and nothing for
    them to remember, and they can change it in the app. It is sent only when the account is
    created, so a password they have since chosen is never overwritten.

    Returns "created", "unchanged" or "failed" (None when there is nothing to do). Never
    raises: a business must not be blocked by SyncUp, and /cron/syncup retries."""
    cfg = syncup_client.config()
    if (person.login_status == AppUser.LOGIN_ACTIVE or not cfg.is_configured
            or not syncup_client.link_base(cfg) or not (person.mobile or person.email)
            or not can_use_app(person)):
        return None
    try:
        links = desired_links(person)
        user = syncup_client.upsert_account(
            person.external_id, name=person.name or person.sign_in,
            password=person.mobile or person.email, is_active=True, links=links,
            **_identity_payload(person))
    except syncup_client.SyncUpError as e:
        log.warning("Opening the app for %s failed: %s", person.external_id, e)
        AppUser.objects.filter(pk=person.pk).update(syncup_error=str(e)[:300])
        return "busy" if e.status == 429 else "failed"
    AppUser.objects.filter(pk=person.pk).update(
        login_status=AppUser.LOGIN_ACTIVE, login_issued_at=timezone.now(), tile_text="",
        syncup_active=True, syncup_synced_at=timezone.now(), syncup_error="",
        identity_pending=False,                 # the account was just made from these values
        identity_sent=identity_signature(person),
        link_keys=",".join(sorted(link["external_id"] for link in links)))
    _note_connection(person, user)
    return "created"


def issue_login(person):
    """Create the login, or re-create it. Returns the password — the only time it exists
    outside SyncUp, so the caller shows it once and never stores it.

    Re-issuing bumps the link token, so a link from an earlier issue stops working."""
    blockers = login_blockers(person)
    if blockers:
        raise LoginBlocked(blockers)
    password = generate_password()
    person.token_version += 1
    # One call: the account and its app link together (SyncUp replaces the link by key).
    # SyncUp knows this person already? Then this becomes a connection they switch on in
    # their app with this password — their account stays theirs.
    _note_connection(person, syncup_client.upsert_account(
        person.external_id, name=person.name or person.sign_in, password=password,
        is_active=True, links=desired_links(person), **_identity_payload(person)))
    person.login_status = AppUser.LOGIN_ACTIVE
    person.login_issued_at = timezone.now()
    person.tile_text = ""            # the new link has no "₹… due" subtitle yet
    _record_sync(person, True)
    person.save()
    return password


def reset_password(person):
    """A new password for an active login, shown once. The link keeps working."""
    if person.login_status != AppUser.LOGIN_ACTIVE:
        raise LoginBlocked(["This person has no active login to reset."])
    password = generate_password()
    active = can_use_app(person)
    syncup_client.upsert_account(person.external_id, name=person.name or person.sign_in,
                                 password=password, is_active=active,
                                 **_identity_payload(person))
    _record_sync(person, active)
    person.save(update_fields=["syncup_active", "syncup_synced_at", "syncup_error"])
    return password


def deactivate_login(person):
    """Switch the login off. Takes effect here immediately — the token is bumped before
    SyncUp is asked — so the /m/ link dies even while SyncUp is unreachable. Returns False
    (with the error recorded for a retry) if SyncUp couldn't be told."""
    person.login_status = AppUser.LOGIN_INACTIVE
    person.web_login = False          # a deactivated login loses web access too
    person.token_version += 1
    person.save(update_fields=["login_status", "web_login", "token_version"])
    try:
        syncup_client.set_account_active(person.external_id, False)
    except syncup_client.SyncUpError as e:
        AppUser.objects.filter(pk=person.pk).update(syncup_error=str(e)[:300])
        return False
    _record_sync(person, False)
    person.save(update_fields=["syncup_active", "syncup_synced_at", "syncup_error"])
    return True


def sync_links(person):
    """Keep their tiles equal to the sides they actually have — a ledger, the staff app, or
    both. Costs nothing while that set is unchanged, which is almost always."""
    links = desired_links(person)
    keys = ",".join(sorted(link["external_id"] for link in links))
    if keys == person.link_keys:
        return False
    if links:
        try:
            syncup_client.upsert_account(
                person.external_id, name=person.name or person.sign_in,
                is_active=can_use_app(person), links=links, **_identity_payload(person))
        except syncup_client.SyncUpError as e:
            log.warning("Tile update for %s failed: %s", person.external_id, e)
            return False
    prune_links(person, {link["external_id"] for link in links})
    AppUser.objects.filter(pk=person.pk).update(link_keys=keys)
    person.link_keys = keys
    return True


def push_identity(person, timeout=None):
    """Tell SyncUp the name, number and email we hold, so they sign in with what the business
    typed. The password is not sent, so one they have chosen stands.

    `timeout` is for the calls made while a business waits (see QUICK_TIMEOUT): their save
    must not hang on SyncUp, and /cron/syncup picks up whatever didn't land.

    Never raises. A 409 means the number already belongs to somebody else's SyncUp account —
    that is recorded against the person and shown on the console."""
    if person.login_status == AppUser.LOGIN_NONE or not syncup_client.config().is_configured:
        return None
    try:
        user = syncup_client.upsert_account(
            person.external_id, name=person.name or person.sign_in,
            is_active=person.syncup_active, links=desired_links(person), timeout=timeout,
            **_identity_payload(person))
    except syncup_client.SyncUpError as e:
        log.warning("New sign-in for %s not accepted: %s", person.external_id, e)
        AppUser.objects.filter(pk=person.pk).update(syncup_error=str(e)[:300])
        return "busy" if e.status == 429 else "failed"
    AppUser.objects.filter(pk=person.pk).update(
        syncup_error="", identity_pending=False, identity_sent=identity_signature(person),
        syncup_synced_at=timezone.now())
    _note_connection(person, user)
    return "pushed"


def refresh_login(person):
    """Keep SyncUp's is_active equal to "the console says active AND they have something to
    open". Called after anything that changes what they can see — a Mobile toggle, a
    business's customer-app switch, a posting, a changed number.

    Never raises: a business must not fail or wait because SyncUp is down. The push is capped
    at QUICK_TIMEOUT and a failure is recorded for /cron/syncup to retry.

    Returns "unchanged", "pushed" or "failed" (None when there's no login to sync)."""
    person = AppUser.objects.filter(pk=person.pk).first()
    if person is None or person.login_status == AppUser.LOGIN_NONE:
        return None
    if identity_drifted(person):
        # What SyncUp holds isn't what we hold — a corrected number, an email added days
        # after the account was made, or a person from before we kept track. Until that has
        # landed nothing else is worth pushing, and the error stands so the cron returns.
        if push_identity(person, timeout=syncup_client.QUICK_TIMEOUT) != "pushed":
            return "failed"
        person.refresh_from_db()
    want = person.login_status == AppUser.LOGIN_ACTIVE and can_use_app(person)
    if person.syncup_active == want and not person.syncup_error:
        return "pushed" if sync_links(person) else "unchanged"
    try:
        _note_connection(person, syncup_client.set_account_active(
            person.external_id, want, timeout=syncup_client.QUICK_TIMEOUT))
    except syncup_client.SyncUpError as e:
        log.warning("SyncUp is_active push failed for %s: %s", person.external_id, e)
        AppUser.objects.filter(pk=person.pk).update(syncup_error=str(e)[:300])
        return "busy" if e.status == 429 else "failed"
    AppUser.objects.filter(pk=person.pk).update(syncup_active=want, syncup_error="",
                                                syncup_synced_at=timezone.now())
    sync_links(person)
    return "pushed"


# SyncUp allows 120 partner calls a minute. A business importing its whole customer list
# would blow through that in seconds, so one run opens at most this many new logins and the
# next run picks up where it left off.
PER_RUN = 100


def link_new_rows(limit=500):
    """Rows pointing at nobody — written before identity.py existed, or imported straight into
    the database without a save. DB only, no SyncUp call, so it costs a cron run nothing.

    A whole live database is better done in one go: `manage.py link_people`. This is the
    trickle that keeps the console honest afterwards."""
    done = 0
    for model in (Customer, Employee):
        for row in model.objects.filter(app_user__isnull=True).order_by("id")[:limit]:
            mobile, email = identity.identifiers(row)
            if (mobile or email) and identity.attach(row):
                done += 1
    return done


def retry_pending():
    """For /cron/syncup: open the app for anyone who can use it but has no login yet, and
    bring every existing login's SyncUp state up to date. Logins already in step cost no
    call.

    When SyncUp answers "too many" the run stops there. Carrying on would only turn a queue
    into a pile of failures, and every person we skip is still waiting in the same place for
    the next run. Returns counts by outcome."""
    counts = {"created": 0, "pushed": 0, "failed": 0, "unchanged": 0, "busy": 0, "left": 0,
              "identity": 0, "linked": link_new_rows()}
    opened = 0
    for person in AppUser.objects.filter(login_status=AppUser.LOGIN_NONE):
        if opened >= PER_RUN:
            break
        outcome = ensure_login(person)
        if outcome:
            counts[outcome] = counts.get(outcome, 0) + 1
            opened += 1
        if outcome == "busy":
            break
    # Everyone still without a login — the ones this run didn't reach, plus the ones who have
    # nothing to open yet. Informational: the next run walks the same list.
    counts["left"] = AppUser.objects.filter(login_status=AppUser.LOGIN_NONE).count()
    # Then everyone who already has one: their state, their tiles, and — the part that
    # matters here — any name, number or email SyncUp was never told about. The run is
    # capped by *calls made*, not people looked at, so a quiet run still walks everybody
    # while the first run after a change works through them a hundred at a time.
    calls, seen = 0, 0
    people = AppUser.objects.exclude(login_status=AppUser.LOGIN_NONE)
    for person in people:
        if calls >= PER_RUN:
            break
        seen += 1
        # Asked before, because refresh_login reports what it did to their *state* — a
        # person whose email we sent and whose state was already right answers "unchanged".
        drifted = identity_drifted(person)
        outcome = refresh_login(person)
        if outcome:
            counts[outcome] = counts.get(outcome, 0) + 1
        if drifted and outcome != "failed":
            counts["identity"] += 1
        if drifted or outcome in ("pushed", "failed", "busy"):
            calls += 1
        if outcome == "busy":
            break
    counts["later"] = max(people.count() - seen, 0)
    return counts


def refresh_people(ids):
    for person in AppUser.objects.filter(id__in=list(ids)).exclude(
            login_status=AppUser.LOGIN_NONE):
        refresh_login(person)


def refresh_for_customer(customer):
    if customer.app_user_id:
        refresh_people([customer.app_user_id])


def refresh_for_employee(employee):
    if employee.app_user_id:
        refresh_people([employee.app_user_id])


def ensure_web_login(employee):
    """Give an EMPLOYEE a GSTSync-native web quick-login, independent of SyncUp: the home
    business copies a /m/ link and the employee opens it in any browser. Creates the local
    AppUser if needed (no SyncUp call). Returns the AppUser, or None when they have no phone
    or email to be identified by."""
    person = identity.attach(employee)
    if person is None:
        return None
    if not person.web_login:
        AppUser.objects.filter(pk=person.pk).update(web_login=True)
        person.web_login = True
    return person


def disable_web_login(employee):
    """Revoke an employee's web quick-login — the copied link dies at once (token bump)."""
    person = employee.app_user
    if person is None or not person.web_login:
        return
    person.web_login = False
    person.token_version += 1
    person.save(update_fields=["web_login", "token_version"])


def refresh_for_business(user):
    """After a business's customer-app switch changes: everyone with a row there."""
    refresh_people(AppUser.objects.filter(customers__user=user)
                   .values_list("id", flat=True).distinct())


def ready_to_issue(person):
    """Shown on the console: a login could be issued right now."""
    return person.login_status != AppUser.LOGIN_ACTIVE and not login_blockers(person)


# --------------------------------------------------------------------------- #
# Console reading
# --------------------------------------------------------------------------- #
def find_people(q):
    """Search people by number, email or name — and by the name on any of their rows."""
    q = (q or "").strip()
    people = AppUser.objects.all()
    if not q:
        return people
    digits = clean_mobile(q)
    email = clean_email(q)
    return people.filter(
        Q(name__icontains=q) | Q(mobile__icontains=digits or q)
        | Q(email__icontains=email or q)
        | Q(customers__customer_name__icontains=q)
        | Q(employees__name__icontains=q)).distinct()
