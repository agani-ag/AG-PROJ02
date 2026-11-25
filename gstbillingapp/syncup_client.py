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
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .models import SyncUpSettings

# The keys SyncUp stores on GSTSync's app links, so re-issuing a login replaces them instead
# of adding more. Links the account holds for other partners are untouched.
#
# A person can be a customer at one business and staff at another — the same number, so the
# same SyncUp account. They get a tile for each side rather than one tile that has to guess.
APP_LINK_KEY = "gstsync"                 # their ledgers
STAFF_LINK_KEY = "gstsync-staff"         # the staff app

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
        # True only when we gave up waiting rather than being refused. The far side may
        # still be working, so a caller must not simply try again.
        self.timed_out = False


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


def _page_title(html):
    """The <title> of an HTML error page, whitespace-collapsed and trimmed — "" if none."""
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    return " ".join(m.group(1).split())[:160] if m else ""


def _request(method, path, payload=None, cfg=None, timeout=None, longer=False):
    """`timeout` normally only LOWERS the console's per-call limit. `longer` lets it raise it
    instead — for the Telegram relay, which retries inside SyncUp and so legitimately takes
    longer than a console call may. Only the cron uses it."""
    cfg = cfg or config()
    limit = cfg.timeout or 5
    if timeout:
        limit = max(timeout, limit) if longer else min(timeout, limit)
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
        body = e.read().decode("utf-8", "replace")
        try:
            data = json.loads(body or "{}")
        except ValueError:
            data = None
        detail = ((data.get("message") if isinstance(data, dict) else None)
                  or _page_title(body) or e.reason)
        if e.code >= 500:
            # SyncUp itself broke. Its error page's title names the exception when its
            # DEBUG page is on (e.g. "OperationalError at /partner/v1/..."), which is usually
            # enough to spot a missing migration.
            raise SyncUpError("SyncUp hit an error on its side (%s): %s. SyncUp's server error "
                              "log has the details." % (e.code, detail),
                              status=e.code, payload=data)
        raise SyncUpError("SyncUp %s %s failed (%s): %s" % (method, path, e.code, detail),
                          status=e.code, payload=data)
    except (urllib.error.URLError, OSError) as e:        # includes timeouts
        raise SyncUpError("SyncUp is unreachable: %s" % e)
    try:
        return json.loads(raw)
    except ValueError:
        raise SyncUpError("SyncUp returned a response that isn't JSON.")


def telegram_document(chat_id, filename, source, caption="", timeout=None):
    """Send a file to a Telegram chat through SyncUp's relay. Returns SyncUp's reply.

    GSTSync has no bot token — SyncUp owns the bot and the send log — so a file leaves here
    the same way a message does.

    The body is the file and nothing else: SyncUp passes those bytes straight to Telegram
    without storing them, which is why everything describing the file travels in the query
    string instead. `source` is the path to the file, or its bytes; a path is read from disk
    in pieces, so a database never has to sit whole in this process's memory.

    The caption is plain text. An operational note is full of dots, slashes and underscores,
    and MarkdownV2 would mean escaping every one of them to say nothing extra."""
    cfg = config()
    if not cfg.is_configured:
        raise SyncUpError("SyncUp isn't set up yet — add its address and partner key under "
                          "Console → Settings.")
    is_path = not isinstance(source, (bytes, bytearray))
    size = os.path.getsize(source) if is_path else len(source)
    if size > TELEGRAM_MAX_DOCUMENT:
        raise SyncUpError("That file is %.1f MB; Telegram accepts up to %d MB from a bot."
                          % (size / 1048576.0, TELEGRAM_MAX_DOCUMENT // 1048576))
    if not size:
        raise SyncUpError("That backup file is empty.")

    query = urllib.parse.urlencode({
        "chat_id": str(chat_id).strip(),
        "filename": filename,
        "caption": (caption or "")[:TELEGRAM_MAX_CAPTION],
    })
    url = cfg.api_base.rstrip("/") + "/partner/v1/telegram/document?" + query
    body = open(source, "rb") if is_path else bytes(source)
    # Content-Length by hand: urllib works it out for bytes, but a file object would make it
    # send chunked instead, which this endpoint refuses.
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": "Bearer " + cfg.partner_key,
        "Content-Type": "application/octet-stream",
        "Content-Length": str(size),
        "Accept": "application/json",
    })
    # An upload is not a page request: it gets its own, longer allowance.
    limit = max(timeout or 0, DOCUMENT_TIMEOUT)
    try:
        try:
            with urllib.request.urlopen(req, timeout=limit) as resp:
                raw = resp.read().decode("utf-8") or "{}"
        finally:
            if is_path:
                body.close()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            data = json.loads(detail or "{}")
        except ValueError:
            data = None
        # The Partner API answers with "message" for a bad request and "error" for a failed
        # delivery. A 413 from PythonAnywhere's own front server is an HTML page, not JSON,
        # so _page_title is the fallback rather than a crash.
        message = ((data.get("error") or data.get("message")) if isinstance(data, dict)
                   else None) or _page_title(detail) or e.reason
        known = {
            404: "This SyncUp doesn't accept documents yet — it needs the "
                 "telegram/document endpoint.",
            403: "SyncUp won't send to that chat: %s. Add the chat to GSTSync's allowed "
                 "list on SyncUp's Telegram page." % message,
            411: "SyncUp needs the file's length and didn't get one (411).",
            413: "The file was refused as too large (413): %s" % message,
            415: "SyncUp expects the file as the raw body (415): %s" % message,
            429: "SyncUp is rate-limiting us (429). The next run will try again.",
            503: "SyncUp's Telegram bot isn't set up: %s" % message,
            # SyncUp streams the bytes through, so it cannot try a second time — a
            # momentary Telegram failure arrives here as a 502, and the next run retries.
            502: "Telegram refused the file: %s" % message,
        }
        raise SyncUpError(known.get(e.code) or "SyncUp refused the file (%s): %s"
                          % (e.code, message), status=e.code, payload=data)
    except (urllib.error.URLError, OSError) as e:
        # A timeout here does NOT mean the send failed — SyncUp keeps going, and sending
        # again would put a second copy of the database in the chat. Callers are told which
        # kind of failure this was so they can leave it alone.
        reason = getattr(e, "reason", e)
        failed = SyncUpError("SyncUp is unreachable: %s" % e)
        failed.timed_out = isinstance(reason, TimeoutError) or isinstance(e, TimeoutError)
        if failed.timed_out:
            failed.args = ("SyncUp didn't answer within %ds. The upload may still have "
                           "reached Telegram, so this won't be retried today."
                           % DOCUMENT_TIMEOUT,)
        raise failed
    try:
        answer = json.loads(raw)
    except ValueError:
        raise SyncUpError("SyncUp returned a response that isn't JSON.")
    if not answer.get("success"):
        raise SyncUpError("Telegram refused the file: %s"
                          % (answer.get("error") or "no reason given"), payload=answer)
    return answer


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


def upsert_account(external_id, *, name, phone=None, email=None, password=None, timeout=None,
                   is_active=True, app_link=None, links=None):
    """Create or update the account in one call (SyncUp's PUT is an idempotent upsert).

    The person is recognised by **their own mobile and/or email** — SyncUp needs at least one.
    An identifier it already knows belongs to a real person: it then gives GSTSync a connection
    to them, which they switch on in their app with this password, and leaves their account's
    own details alone. Sending a phone and an email that belong to two different people is
    refused (409) rather than guessed at.

    Creating needs a password; updating only changes the password when one is given. With
    `app_link`, the same call sets the account's GSTSync link (replaced by its key), and the
    reply is checked for it: an older SyncUp that doesn't understand links would otherwise
    leave the person with a login and nothing to open."""
    payload = {"name": name, "is_active": bool(is_active)}
    if phone:
        payload["phone"] = phone
    if email:
        payload["email"] = email
    if password:
        payload["password"] = password
    wanted = list(links) if links else ([{"external_id": APP_LINK_KEY, "title": "GSTSync",
                                          "url": app_link, "icon": "home"}] if app_link else [])
    if wanted:
        payload["links"] = wanted
    data = _request("PUT", "users/external/%s" % external_id, payload, timeout=timeout)
    got = {(link or {}).get("url") for link in (data.get("links") or [])}
    if wanted and not all(w["url"] in got for w in wanted):
        raise SyncUpError("SyncUp saved the account but not its app link. SyncUp may need "
                          "updating to the Partner API with link upserts.")
    return data.get("user") or {}


def set_account_active(external_id, is_active, timeout=None):
    """Switch an existing account on or off without touching anything else. `timeout`
    lowers the wait for pushes made on a business's behalf (see QUICK_TIMEOUT)."""
    return _request("PUT", "users/external/%s" % external_id,
                    {"is_active": bool(is_active)}, timeout=timeout).get("user") or {}


def notify_bulk(messages, timeout=None):
    """Send many pushes in one call — each `{external_id, title, body, url}`. Returns SyncUp's
    per-message results in the same order (`{"delivered": n}` or `{"error": …}`)."""
    return _request("POST", "notify/bulk", {"messages": messages},
                    timeout=timeout).get("results") or []


def create_action(external_id, payload, timeout=None):
    """Send a prompt (e.g. `{"type": "approve", …}`). Returns SyncUp's reply with request_id."""
    return _request("POST", "users/external/%s/action" % external_id, payload, timeout=timeout)


def action_status(request_id, timeout=None):
    """A prompt's state and answer — for an answer whose callback never arrived."""
    return _request("GET", "actions/%s" % request_id, timeout=timeout)


def list_links(external_id, timeout=None):
    """The links GSTSync has put on this account, each with its SyncUp id and our own key."""
    return _request("GET", "users/external/%s/links" % external_id,
                    timeout=timeout).get("links") or []


def delete_link(link_id, timeout=None):
    """Remove one of our links — used when somebody stops being staff (or a customer) and
    their tile for that side should go with it."""
    return _request("DELETE", "links/%s" % link_id, timeout=timeout)


def update_app_link(external_id, *, url, description, timeout=None):
    """Change only the GSTSync tile (e.g. its "₹… due" subtitle); the account is untouched."""
    return _request("PUT", "users/external/%s" % external_id, {"links": [{
        "external_id": APP_LINK_KEY, "title": "GSTSync", "url": url, "icon": "home",
        "description": description,
    }]}, timeout=timeout)


# --------------------------------------------------------------------------- #
# Telegram relay — SyncUp's bot posts our reports to a chat id we supply
# --------------------------------------------------------------------------- #
# A Telegram send retries inside SyncUp (3 tries, short backoff), so these calls are given more
# room than a console call. They only ever run from /cron/syncup or a console test.
TELEGRAM_TIMEOUT = 20
# A whole database crossing two hosts on its way to Telegram. Nothing waits on this — it
# runs after the cron's reply has gone — so it gets an allowance a page never would.
# SyncUp allows Telegram 60s a try and tries three times, so the far side can legitimately
# take three minutes. Anything under that would time us out while the send is still working.
DOCUMENT_TIMEOUT = 240
TELEGRAM_MAX_DOCUMENT = 50 * 1048576            # Telegram's limit for a bot upload
TELEGRAM_MAX_CAPTION = 1024


def telegram_send(chat_id, text, parse_mode="MarkdownV2", timeout=TELEGRAM_TIMEOUT,
                  longer=True):
    """One message to one chat. Returns SyncUp's reply (it carries Telegram's message_id).

    SyncUp answers 502 when Telegram refused (bad chat id, bot removed), and 503 when no bot is
    set up on its side — both arrive here as SyncUpError with that status."""
    return _request("POST", "telegram/send",
                    {"chat_id": str(chat_id), "text": text, "parse_mode": parse_mode},
                    timeout=timeout, longer=longer)


def telegram_bulk(messages, timeout=TELEGRAM_TIMEOUT, longer=True):
    """Many messages in one call — each `{chat_id, text, parse_mode}`. Returns the per-message
    results in the same order (`{"chat_id", "message_id"}` or `{"chat_id", "error"}`).

    `longer=False` caps the wait instead of extending it — for the one quick try a login alert
    makes while somebody is signing in."""
    return _request("POST", "telegram/bulk", {"messages": messages},
                    timeout=timeout, longer=longer).get("results") or []
