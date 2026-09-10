"""Client for SyncUp's Partner API (AG-PROJ01, mounted at /partner/v1/).

GSTSync is one SyncUp partner. Each customer login is a SyncUp account that GSTSync creates
and addresses by its own id — external_id "party-<id>" — so GSTSync never needs SyncUp's
internal ids. SyncUp stores the password hash and performs the actual login; GSTSync only
ever sends a password when issuing or resetting one.

Where SyncUp is, the partner key, this site's public address and the timeout all come from
the database (models.SyncUpSettings, edited under Console → Settings), not settings.py, so
an admin can set them up without server access or a restart.

Standard library only (urllib), so this adds no dependency. Every call has a short timeout
and raises SyncUpError on any failure. Callers decide what a failure means: a console action
reports it, while a business-side toggle only records it — a business must never be blocked,
or kept waiting, because SyncUp is down.
"""
import json
import urllib.error
import urllib.request

from .models import SyncUpSettings


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


def _request(method, path, payload=None, cfg=None):
    cfg = cfg or config()
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
        with urllib.request.urlopen(req, timeout=cfg.timeout or 5) as resp:
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
    the partner key?

    Looks up an account that can't exist. SyncUp answers that with its own JSON 404 once
    the key is accepted, and with 401 when it isn't. Nothing is created or changed on
    either side."""
    ok_msg = "Connected — SyncUp accepted the partner key."
    try:
        _request("GET", "users/external/gstsync-connection-check", cfg=cfg)
        return True, ok_msg
    except SyncUpError as e:
        from_syncup = isinstance(e.payload, dict) and "success" in e.payload
        if e.status == 404 and from_syncup:
            return True, ok_msg
        if e.status == 429 and from_syncup:
            return True, "Connected — the key is accepted, but SyncUp is rate-limiting right now."
        if e.status == 401:
            return False, "SyncUp rejected the partner key."
        if e.status == 404:
            return False, ("Something answered at that address, but it isn't SyncUp's Partner "
                           "API. Check the SyncUp address.")
        return False, str(e)


def upsert_account(external_id, *, name, email, password=None, is_active=True):
    """Create or update the account (SyncUp's PUT is an idempotent upsert).

    Creating needs a password; updating only changes the password when one is given."""
    payload = {"name": name, "email": email, "is_active": bool(is_active)}
    if password:
        payload["password"] = password
    return _request("PUT", "users/external/%s" % external_id, payload).get("user") or {}


def set_account_active(external_id, is_active):
    """Switch an existing account on or off without touching anything else."""
    return _request("PUT", "users/external/%s" % external_id,
                    {"is_active": bool(is_active)}).get("user") or {}


def list_links(external_id):
    return _request("GET", "users/external/%s/links" % external_id).get("links") or []


def add_link(external_id, *, title, url, icon=""):
    return _request("POST", "users/external/%s/links" % external_id,
                    {"title": title, "url": url, "icon": icon}).get("link") or {}


def delete_link(link_id):
    _request("DELETE", "links/%s" % link_id)


def replace_link(external_id, *, title, url, prefix, icon="home"):
    """Make `url` the account's one GSTSync link: remove our earlier links (any URL under
    `prefix`, which carries an older token) and add the new one. Links the account holds
    for other purposes are left alone."""
    for link in list_links(external_id):
        if (link.get("url") or "").startswith(prefix):
            delete_link(link["id"])
    return add_link(external_id, title=title, url=url, icon=icon)
