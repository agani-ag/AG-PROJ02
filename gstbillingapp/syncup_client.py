"""Client for SyncUp's Partner API (AG-PROJ01, mounted at /partner/v1/).

GSTSync is one SyncUp partner. Each login is a SyncUp account that GSTSync creates and
addresses by its own id — external_id "party-<id>" for customers, "employee-<id>" for
staff — so GSTSync never needs SyncUp's internal ids. SyncUp stores the password hash and
performs the actual login; GSTSync only ever sends a password when issuing or resetting one.

Every GSTSync action is ONE Partner API call. Issuing a login sends the account and its app
link together: SyncUp's upsert replaces the link by its key ("gstsync"), so there is no
list-then-delete-then-add round trip.

Where SyncUp is, the partner key, this site's public address and the timeout all come from
the database (models.SyncUpSettings, edited under Console → Settings), not settings.py.

Standard library only (urllib), so this adds no dependency. Every call has a short timeout
and raises SyncUpError on any failure. Callers decide what a failure means: a console action
reports it, while a business-side change only records it — a business must never be blocked
because SyncUp is down.
"""
import json
import time
import urllib.error
import urllib.request

from .models import SyncUpSettings

# The key SyncUp stores on GSTSync's app link, so re-issuing a login replaces that link
# instead of adding a second one. Links the account holds for other purposes are untouched.
APP_LINK_KEY = "gstsync"

# Pushes made on a business's behalf (a Mobile toggle, an Active switch) wait at most this
# long, whatever the console's timeout: a failure is recorded and /cron/syncup retries it,
# so a business never sits waiting on SyncUp. (No background thread: PythonAnywhere-style
# uWSGI hosting runs web apps without thread support.)
QUICK_TIMEOUT = 2


class SyncUpError(Exception):
    """A Partner API call failed, timed out, or SyncUp isn't set up.

    `status` is the HTTP status when SyncUp (or whatever answered) returned one, and
    `payload` the decoded JSON body when there was one."""

    def __init__(self, message, status=None, payload=None):
        super().__init__(message)
        self.status = status
        self.payload = payload


def config():
    """The current settings row (unsaved defaults until an admin saves the screen)."""
    return SyncUpSettings.load()


def is_configured(cfg=None):
    return (cfg or config()).is_configured


def link_base(cfg=None):
    """The public https:// address of this site, or "" when it isn't set correctly.

    SyncUp rejects non-https link URLs, so the /m/ link is built from this setting rather
    than from whatever address the console happens to be opened on."""
    base = ((cfg or config()).link_base or "").strip().rstrip("/")
    return base if base.lower().startswith("https://") else ""


def _request(method, path, payload=None, cfg=None, timeout=None):
    cfg = cfg or config()
    limit = cfg.timeout or 5
    if timeout:
        limit = min(timeout, limit)
    if not cfg.is_configured:
        raise SyncUpError("SyncUp isn't set up yet — add its address and partner key under "
                          "Console → Settings.")
    url = cfg.api_base.rstrip("/") + "/partner/v1/" + path.lstrip("/")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": "Bearer " + cfg.partner_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=limit) as resp:
            raw = resp.read().decode("utf-8") or "{}"
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read().decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            data = None
        detail = (data.get("message") if isinstance(data, dict) else None) or e.reason
        raise SyncUpError("SyncUp %s %s failed (%s): %s" % (method, path, e.code, detail),
                          status=e.code, payload=data)
    except (urllib.error.URLError, OSError) as e:        # includes timeouts
        raise SyncUpError("SyncUp is unreachable: %s" % e)
    try:
        return json.loads(raw)
    except ValueError:
        raise SyncUpError("SyncUp returned a response that isn't JSON.")


def check_connection(cfg=None):
    """(ok, message) — is SyncUp reachable at the configured address, and does it accept
    the partner key? The message includes the round-trip time.

    Looks up an account that can't exist. SyncUp answers that with its own JSON 404 once
    the key is accepted, and with 401 when it isn't. Nothing is created or changed on
    either side."""
    started = time.perf_counter()

    def took():
        return " (%d ms)" % round((time.perf_counter() - started) * 1000)

    ok_msg = "Connected — SyncUp accepted the partner key"
    try:
        _request("GET", "users/external/gstsync-connection-check", cfg=cfg)
        return True, ok_msg + took() + "."
    except SyncUpError as e:
        from_syncup = isinstance(e.payload, dict) and "success" in e.payload
        if e.status == 404 and from_syncup:
            return True, ok_msg + took() + "."
        if e.status == 429 and from_syncup:
            return True, ("Connected%s — the key is accepted, but SyncUp is rate-limiting "
                          "right now." % took())
        if e.status == 401:
            return False, "SyncUp rejected the partner key%s." % took()
        if e.status == 404:
            return False, ("Something answered at that address, but it isn't SyncUp's Partner "
                           "API. Check the SyncUp address.")
        return False, str(e)


def upsert_account(external_id, *, name, email, password=None, is_active=True, app_link=None):
    """Create or update the account in one call (SyncUp's PUT is an idempotent upsert).

    Creating needs a password; updating only changes the password when one is given. With
    `app_link`, the same call sets the account's GSTSync link (replaced by its key), and the
    reply is checked for it: an older SyncUp that doesn't understand links would otherwise
    leave the customer with a login and nothing to open."""
    payload = {"name": name, "email": email, "is_active": bool(is_active)}
    if password:
        payload["password"] = password
    if app_link:
        payload["links"] = [{"external_id": APP_LINK_KEY, "title": "GSTSync",
                             "url": app_link, "icon": "home"}]
    data = _request("PUT", "users/external/%s" % external_id, payload)
    if app_link and not any((link or {}).get("url") == app_link
                            for link in (data.get("links") or [])):
        raise SyncUpError("SyncUp saved the account but not its app link. SyncUp may need "
                          "updating to the Partner API with link upserts.")
    return data.get("user") or {}


def set_account_active(external_id, is_active, timeout=None):
    """Switch an existing account on or off without touching anything else. `timeout`
    lowers the wait for pushes made on a business's behalf (see QUICK_TIMEOUT)."""
    return _request("PUT", "users/external/%s" % external_id,
                    {"is_active": bool(is_active)}, timeout=timeout).get("user") or {}
