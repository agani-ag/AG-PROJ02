"""Business passkeys — a 5-character sign-in shortcut, set per business on the console.

Replaces a list of passkeys that used to be hard-coded in views/auth.py (and so sits in the
Git history). Rules:

  * exactly 5 letters or digits, case-insensitive;
  * not all one character, not a straight run (12345, ABCDE, and backwards), and never one
    of the old published passkeys;
  * unique across businesses — the passkey alone identifies the business;
  * stored only as a keyed digest, shown once when set;
  * wrong tries are limited per device (5 per 15 minutes).
"""
import hashlib
import hmac
import secrets

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError

from .models import BusinessPasskey, UserProfile

LENGTH = 5
ALLOWED = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
# Generated passkeys skip look-alikes (0/O, 1/I/L) so they're easy to read out over a call.
GENERATED = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
# The old hard-coded list. Public in the Git history, so refused forever.
LEAKED = frozenset({"11111", "22222", "33333", "44444", "55555", "97911"})

MAX_TRIES = 5
WINDOW_SECONDS = 15 * 60


def normalise(value):
    return (value or "").strip().upper() if isinstance(value, str) else ""


def digest(passkey):
    """HMAC-SHA256 of the passkey under a key derived from SECRET_KEY. Deterministic, so the
    business can be looked up from the passkey alone; useless without the server's secret."""
    key = hashlib.sha256(("gstsync-passkey:" + settings.SECRET_KEY).encode()).digest()
    return hmac.new(key, normalise(passkey).encode(), hashlib.sha256).hexdigest()


def _is_run(p):
    return any(p in seq or p in seq[::-1] for seq in ("0123456789", "ABCDEFGHIJKLMNOPQRSTUVWXYZ"))


def problem(passkey, *, business=None):
    """Why this passkey can't be used — "" when it can. `business` is the one it's for, so
    its own current passkey doesn't count as taken."""
    p = normalise(passkey)
    if len(p) != LENGTH or any(ch not in ALLOWED for ch in p):
        return "A passkey is exactly 5 letters or digits."
    if p in LEAKED:
        return "That passkey was published before, so it can't be used."
    if len(set(p)) == 1:
        return "All one character is too easy to guess."
    if _is_run(p):
        return "A straight run like 12345 or ABCDE is too easy to guess."
    taken = BusinessPasskey.objects.filter(digest=digest(p))
    if business is not None:
        taken = taken.exclude(user=business)
    if taken.exists():
        return "Another business already uses that passkey."
    return ""


def generate():
    """A random passkey that passes every rule."""
    while True:
        p = "".join(secrets.choice(GENERATED) for _ in range(LENGTH))
        if not problem(p):
            return p


def set_passkey(business, passkey, admin=None):
    """Set (or replace) a business's passkey. Returns it normalised, for showing once.
    Raises ValueError with the reason when it breaks a rule."""
    p = normalise(passkey)
    reason = problem(p, business=business)
    if reason:
        raise ValueError(reason)
    try:
        BusinessPasskey.objects.update_or_create(
            user=business, defaults={"digest": digest(p), "set_by": admin, "last_used_at": None})
    except IntegrityError:                      # another business took it a moment ago
        raise ValueError("Another business already uses that passkey.")
    return p


def turn_off(business):
    BusinessPasskey.objects.filter(user=business).delete()


def authenticate(passkey):
    """The BusinessPasskey this passkey opens, or None — wrong, turned off, or the business
    is suspended or has no profile."""
    p = normalise(passkey)
    if len(p) != LENGTH:
        return None
    record = BusinessPasskey.objects.select_related("user").filter(digest=digest(p)).first()
    if record is None or not record.user.is_active:
        return None
    if not UserProfile.objects.filter(user=record.user).exists():
        return None
    return record


# ---- attempt limit (per device) -------------------------------------------------------
def _tries_key(request):
    # Behind the hosting proxy (PythonAnywhere) every request shares REMOTE_ADDR, and the
    # proxy puts the visitor's own address in X-Real-IP.
    ip = request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or "?"
    return "passkey-tries:" + ip


def too_many_tries(request):
    return cache.get(_tries_key(request), 0) >= MAX_TRIES


def record_failure(request):
    key = _tries_key(request)
    cache.set(key, cache.get(key, 0) + 1, WINDOW_SECONDS)


def clear_failures(request):
    cache.delete(_tries_key(request))
