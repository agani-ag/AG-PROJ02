"""Real-time active-device presence + device history.

Lightweight, WSGI-friendly (no WebSockets/Channels): every open browser of a
logged-in user sends a periodic heartbeat to ``presence_ping``. A device counts as
ONLINE while its ``last_seen`` is within PRESENCE_WINDOW; when the browser closes the
heartbeat stops and it goes offline on its own.

Rows are kept as a per-device history (not deleted on logout), so the profile page can
show each device with its online/offline state, when it was first seen and last seen.
A device is recognised again on return because its ``token`` (a random id kept in the
browser's localStorage) is reused across logins on that browser. Long-idle rows are
pruned by the nightly cron (see cleanup.purge_stale_devices).
"""
import json
import os
import tempfile
import time
import uuid
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ..models import ActiveDevice

# Heartbeat cadence lives in the browser (~30s). Keep the window a little over 2x
# so a single missed beat never makes a live device flicker offline.
PRESENCE_WINDOW = timedelta(seconds=75)

# --------------------------------------------------------------------------- #
# A note between your own devices
# --------------------------------------------------------------------------- #
# Signed in on the shop computer and on your phone, you can put a line on both screens at
# once. It rides the heartbeat that is already running, so it costs no new polling.
#
# Both ends can talk: a line from the counter, a line back from the phone. It keeps no
# history — everything older than a minute is simply dropped — so this lives in a file in
# the system temp directory rather than in the database. Nothing here is worth a table, a
# migration, or a row somebody has to clean up later.
#
# A file rather than the cache, because this installation has no CACHES setting and so uses
# Django's per-process LocMemCache: two workers would not see each other's writes, which is
# exactly the thing this has to do.
NOTE_LIFE = 60                                   # a minute, then the line is gone
NOTE_MAX = 280
THREAD_MAX = 20                                  # a minute can't hold more than a handful


def _note_path(user_id):
    return os.path.join(tempfile.gettempdir(), "gstsync-note-%d.json" % int(user_id))


def _load(user_id):
    try:
        with open(_note_path(user_id), "r", encoding="utf-8") as f:
            lines = json.load(f)
    except (OSError, ValueError):
        return []
    return lines if isinstance(lines, list) else []


def _fresh(lines):
    cutoff = time.time() - NOTE_LIFE
    return [n for n in lines if isinstance(n, dict) and n.get("at", 0) > cutoff]


def read_notes(user_id):
    """Everything said in the last minute, oldest first. The browser gets no timestamps it
    doesn't need — just enough to tell one line from the next, and whose it was."""
    return [{k: v for k, v in n.items() if k != "at"} for n in _fresh(_load(user_id))]


def add_note(user_id, text, sender="", device=""):
    """Add a line to what this person's screens are showing, and return the lot.

    Read, add, write — two devices typing in the same instant could in theory lose one. For
    a line that disappears in a minute, a lock would cost more than it saves."""
    lines = _fresh(_load(user_id))
    lines.append({"id": uuid.uuid4().hex[:10], "text": text[:NOTE_MAX], "from": sender,
                  "by": device, "at": time.time(),
                  "when": timezone.localtime().strftime("%I:%M %p").lstrip("0")})
    lines = lines[-THREAD_MAX:]
    path = _note_path(user_id)
    # Written beside and moved into place, so a device reading at the wrong moment gets the
    # old set or the new one, never half of either.
    fd, temp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".note")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(lines, f)
        os.replace(temp, path)
    except OSError:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
    return [{k: v for k, v in n.items() if k != "at"} for n in lines]


def clear_note(user_id):
    try:
        os.unlink(_note_path(user_id))
    except OSError:
        pass


def _active_count(user):
    """How many of ``user``'s devices are online right now (seen within the window)."""
    cutoff = timezone.now() - PRESENCE_WINDOW
    return ActiveDevice.objects.filter(user=user, last_seen__gte=cutoff).count()


def device_name(ua):
    """A friendly 'Browser on OS' label derived from the user-agent string."""
    ua = ua or ""
    if "Windows" in ua:
        os_ = "Windows"
    elif "iPhone" in ua:
        os_ = "iPhone"
    elif "iPad" in ua:
        os_ = "iPad"
    elif "Android" in ua:
        os_ = "Android"
    elif "Mac OS" in ua or "Macintosh" in ua:
        os_ = "Mac"
    elif "Linux" in ua:
        os_ = "Linux"
    else:
        os_ = "Unknown device"

    if "Edg" in ua:
        br = "Edge"
    elif "OPR" in ua or "Opera" in ua:
        br = "Opera"
    elif "SamsungBrowser" in ua:
        br = "Samsung Internet"
    elif "Chrome" in ua:
        br = "Chrome"
    elif "Firefox" in ua:
        br = "Firefox"
    elif "Safari" in ua:
        br = "Safari"
    else:
        br = "Browser"
    return "%s on %s" % (br, os_)


def device_info(user):
    """Every known device for ``user`` (online first, then most-recently-seen)."""
    now = timezone.now()
    window = PRESENCE_WINDOW
    rows = ActiveDevice.objects.filter(user=user)
    out = []
    for r in rows:
        online = (now - r.last_seen) <= window
        out.append({
            "token": r.token,  # the caller's own account only; client matches its own id
            "name": device_name(r.user_agent),
            "user_agent": r.user_agent,
            "online": online,
            "last_seen": timezone.localtime(r.last_seen).strftime("%d %b %Y, %I:%M %p"),
            "first_seen": timezone.localtime(r.created_at).strftime("%d %b %Y, %I:%M %p"),
            "_sort": r.last_seen,
        })
    out.sort(key=lambda d: (not d["online"], -d["_sort"].timestamp()))
    for d in out:
        d.pop("_sort", None)
    return out


@login_required
@require_POST
def presence_ping(request):
    """Heartbeat: refresh (or create) this device's row and return the live count."""
    token = (request.POST.get("token") or "").strip()[:64]
    if not token:
        return JsonResponse({"error": "missing token"}, status=400)

    ua = (request.META.get("HTTP_USER_AGENT") or "")[:300]
    ActiveDevice.objects.update_or_create(
        user=request.user, token=token,
        defaults={"user_agent": ua},  # last_seen refreshes via auto_now
    )
    request.session["device_token"] = token
    # The note rides the beat that was happening anyway: no second timer, no new endpoint
    # being polled, and a device that has just come back picks up whatever is current.
    return JsonResponse({"count": _active_count(request.user),
                         "notes": read_notes(request.user.id)})


@login_required
@require_POST
def presence_say(request):
    """Say one line to every screen this person is signed in on, including this one.

    Either end can talk, so what comes back is the whole last minute, not just the line
    that was added. Posting an empty line clears the lot."""
    text = (request.POST.get("text") or "").strip()
    if not text:
        clear_note(request.user.id)
        return JsonResponse({"ok": True, "notes": []})
    if len(text) > NOTE_MAX:
        return JsonResponse({"ok": False,
                             "error": "Keep it under %d characters." % NOTE_MAX}, status=400)
    sender = device_name(request.META.get("HTTP_USER_AGENT") or "")
    device = (request.POST.get("token") or request.session.get("device_token") or "")[:64]
    return JsonResponse({"ok": True,
                         "notes": add_note(request.user.id, text, sender, device)})


@login_required
@require_POST
def presence_list(request):
    """The current user's full device list + live online count (for the profile page)."""
    return JsonResponse({
        "count": _active_count(request.user),
        "devices": device_info(request.user),
    })


@csrf_exempt
@require_POST
def presence_leave(request):
    """Sent via navigator.sendBeacon on tab close so the online count drops promptly.

    It does NOT delete the row (that history is kept) — it backdates last_seen just past
    the online window, so the device reads as offline immediately while its "last seen"
    still reflects that it was active moments ago. CSRF-exempt because sendBeacon cannot
    set headers; safe because it only touches the authenticated user's own row.
    """
    if request.user.is_authenticated:
        token = (request.POST.get("token") or "").strip()[:64]
        if token:
            stamp = timezone.now() - PRESENCE_WINDOW - timedelta(seconds=1)
            # .update() bypasses auto_now so the backdated stamp sticks.
            ActiveDevice.objects.filter(user=request.user, token=token).update(last_seen=stamp)
    return HttpResponse(status=204)
