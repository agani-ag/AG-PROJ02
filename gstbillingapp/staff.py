"""Employee logins for the SyncUp app — issued, reset and switched off from the console.

An Employee is already one person across every business they're posted to (home + shared
postings), so unlike customers (see parties.py) there's nothing to map: each person gets
one login, gse{id}@<login domain>, and its link opens /m/employee/ with all their
businesses.

Who controls what:
  * The console issues, resets and deactivates the login. Businesses no longer hand out
    employee app links.
  * The home business's Active switch still rules access: turning the person off stops
    their login, turning them back on restores it (no new password needed).

SyncUp's is_active = the console's status AND the person is active. It's pushed whenever
either changes; a failure is recorded on the login and retried, and never blocks or slows
down a business.
"""
import logging

from django.db import transaction
from django.db.models import F
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone

from . import syncup_client
from .mobile_auth import mint_employee_token
from .models import Employee, StaffLogin
from .parties import LoginBlocked
from .passwords import generate_customer_password

log = logging.getLogger(__name__)


def login_of(employee):
    """The employee's StaffLogin, or an unsaved one meaning "no login yet"."""
    try:
        return employee.staff_login
    except StaffLogin.DoesNotExist:
        return StaffLogin(employee=employee)


def app_link_prefix():
    return syncup_client.link_base() + "/m/employee/"


def app_link(employee):
    return app_link_prefix() + "?t=" + mint_employee_token(employee)


def login_blockers(employee):
    """Why a login can't be issued right now — empty when it can."""
    reasons = []
    cfg = syncup_client.config()
    if not cfg.is_configured:
        reasons.append("SyncUp isn't set up yet — add its address and partner key under "
                       "Settings.")
    if not syncup_client.link_base(cfg):
        reasons.append("Set this site's public https:// address under Settings — the app "
                       "link is built from it.")
    if not employee.is_active:
        reasons.append("%s is switched off at their home business. Turn them back on there "
                       "first." % employee.name)
    return reasons


def _record(login, active):
    login.syncup_active = active
    login.syncup_synced_at = timezone.now()
    login.syncup_error = ""


def issue_login(employee):
    """Create the login, or re-create it. Returns the new password — shown once by the
    caller, never stored. A fresh link token is minted, so every older link (including
    ones businesses shared before logins moved to the console) stops working."""
    blockers = login_blockers(employee)
    if blockers:
        raise LoginBlocked(blockers)
    login = login_of(employee)
    password = generate_customer_password()
    employee.token_version += 1                     # saved only once SyncUp has accepted
    # One call: the account and its app link together (SyncUp replaces the link by key).
    syncup_client.upsert_account(login.external_id, name=employee.name, email=login.login_email,
                                 password=password, is_active=True, app_link=app_link(employee))
    # A queryset update: Employee.save() also re-normalises the person's details.
    Employee.objects.filter(pk=employee.pk).update(token_version=employee.token_version)
    login.login_status = StaffLogin.LOGIN_ACTIVE
    login.login_issued_at = timezone.now()
    _record(login, True)
    login.save()
    return password


def reset_password(employee):
    """A new password for an active login, shown once. The link keeps working."""
    login = login_of(employee)
    if login.login_status != StaffLogin.LOGIN_ACTIVE:
        raise LoginBlocked(["This employee has no active login to reset."])
    password = generate_customer_password()
    syncup_client.upsert_account(login.external_id, name=employee.name, email=login.login_email,
                                 password=password, is_active=employee.is_active)
    _record(login, employee.is_active)
    login.save()
    return password


def deactivate_login(employee):
    """Switch the login off. The link dies here at once (token bumped before SyncUp is
    asked), so it works even while SyncUp is unreachable. Returns False — with the error
    recorded for a retry — if SyncUp couldn't be told."""
    login = login_of(employee)
    login.login_status = StaffLogin.LOGIN_INACTIVE
    Employee.objects.filter(pk=employee.pk).update(token_version=F("token_version") + 1)
    employee.refresh_from_db(fields=["token_version"])
    login.save()
    try:
        syncup_client.set_account_active(login.external_id, False)
    except syncup_client.SyncUpError as e:
        StaffLogin.objects.filter(pk=login.pk).update(syncup_error=str(e)[:300])
        return False
    _record(login, False)
    login.save(update_fields=["syncup_active", "syncup_synced_at", "syncup_error"])
    return True


def refresh_login(employee):
    """Keep SyncUp's is_active equal to "console says active AND the person is active".
    Called when a home business switches someone on or off. Makes no call when nothing
    changed, and NEVER raises — a business must not fail or wait long because SyncUp is
    down: the push is capped at QUICK_TIMEOUT and a failure is retried by /cron/syncup.

    Returns "unchanged", "pushed" or "failed" (None when there's no login to sync)."""
    login = StaffLogin.objects.filter(employee_id=employee.pk).first()
    if login is None or login.login_status == StaffLogin.LOGIN_NONE:
        return None
    person_active = Employee.objects.filter(pk=employee.pk, is_active=True).exists()
    want = login.login_status == StaffLogin.LOGIN_ACTIVE and person_active
    if login.syncup_active == want and not login.syncup_error:
        return "unchanged"
    try:
        syncup_client.set_account_active(login.external_id, want,
                                         timeout=syncup_client.QUICK_TIMEOUT)
    except syncup_client.SyncUpError as e:
        log.warning("SyncUp is_active push failed for %s: %s", login.external_id, e)
        StaffLogin.objects.filter(pk=login.pk).update(syncup_error=str(e)[:300])
        return "failed"
    StaffLogin.objects.filter(pk=login.pk).update(syncup_active=want, syncup_error="",
                                                  syncup_synced_at=timezone.now())
    return "pushed"


def retry_pending():
    """Bring every employee login's SyncUp state up to date — for /cron/syncup. Returns
    counts by outcome."""
    counts = {"pushed": 0, "failed": 0, "unchanged": 0}
    for login in StaffLogin.objects.exclude(login_status=StaffLogin.LOGIN_NONE) \
            .select_related("employee"):
        outcome = refresh_login(login.employee)
        if outcome:
            counts[outcome] += 1
    return counts


@receiver(pre_delete, sender=Employee, dispatch_uid="staff_login_employee_deleted")
def _switch_off_deleted_employee(sender, instance, **kwargs):
    """A deleted employee's SyncUp login must not outlive them. Their StaffLogin row goes
    with them (CASCADE), so SyncUp is told here — once the delete commits, and quietly: a
    business removing an employee (or a business purge) never fails because SyncUp is
    down. Wired up in apps.GstbillingappConfig.ready()."""
    login = StaffLogin.objects.filter(employee_id=instance.pk).first()
    if login is None or (login.syncup_active is False and not login.syncup_error):
        return
    external_id = login.external_id

    def push():
        try:
            syncup_client.set_account_active(external_id, False,
                                             timeout=syncup_client.QUICK_TIMEOUT)
        except syncup_client.SyncUpError as e:
            log.warning("Couldn't switch off %s in SyncUp after deletion: %s", external_id, e)

    transaction.on_commit(push)
