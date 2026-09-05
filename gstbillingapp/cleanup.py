"""Database maintenance — shared by `manage.py cleanup_db` and the /cron/ endpoints.

There is no in-process scheduler: an external HTTP cron service pings the endpoints in
cron_views.py on a schedule. That shapes the design, because such a service can and will
call a URL twice — it retries on timeout, and two ticks overlap whenever a run outlasts
its interval. So every job here is

  * single-flight — a lockfile stops overlapping runs (deliberately NOT a DB table, so
                    this ships without a migration),
  * idempotent   — re-running changes nothing that a previous run already did,
  * bounded      — the work is a handful of bulk statements on a small SQLite file,
  * honest       — each job returns a stats dict of what it actually did.

What is deliberately NOT automated: no invoice, booklog or inventorylog is ever deleted
here. Those are business and audit records and there is no retention rule for them.

Old quotations ARE purgeable, but only when explicitly asked for (a `quotation_days`
argument — never by default). Every status goes once past the window; see
purge_quotations() for what that gives up and why it is safe for the financial record.
"""
import os
import glob
import errno
import shutil
import datetime

from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.utils import timezone
from django.contrib.sessions.models import Session

from .models import Quotation, ActiveDevice


# --------------------------------------------------------------------------- #
# Single-flight lock
# --------------------------------------------------------------------------- #
# Longer than any single run, short enough that a crashed run frees the lock soon after.
LOCK_TTL_SECONDS = 15 * 60


def _lock_path(name):
    return os.path.join(settings.BASE_DIR, ".cron-%s.lock" % name)


class LockBusy(Exception):
    """Another run of this job is still going."""


class job_lock(object):
    """Context manager taking an exclusive lockfile for `name`.

    O_CREAT|O_EXCL is atomic on both Windows and POSIX, so two workers can't both win.
    A lock older than LOCK_TTL_SECONDS is assumed to belong to a run that died mid-flight
    (crash, deploy, aborted HTTP call) and is stolen.
    """

    def __init__(self, name, ttl_seconds=LOCK_TTL_SECONDS):
        self.name = name
        self.ttl = ttl_seconds
        self.path = _lock_path(name)

    def __enter__(self):
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
            # Held. Steal it only if the holder has outlived its TTL.
            try:
                age = _now_ts() - os.path.getmtime(self.path)
            except OSError:
                age = None
            if age is None or age < self.ttl:
                raise LockBusy(self.name)
            os.unlink(self.path)
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except OSError:
                raise LockBusy(self.name)
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        return self

    def __exit__(self, *exc):
        try:
            os.unlink(self.path)
        except OSError:
            pass
        return False


def _now_ts():
    return datetime.datetime.now().timestamp()


def last_run(name):
    """When this job last finished, or None. Read from the marker the job leaves behind."""
    path = os.path.join(settings.BASE_DIR, ".cron-%s.last" % name)
    try:
        return timezone.make_aware(
            datetime.datetime.fromtimestamp(os.path.getmtime(path)),
            timezone.get_default_timezone())
    except OSError:
        return None


def _mark_run(name):
    path = os.path.join(settings.BASE_DIR, ".cron-%s.last" % name)
    with open(path, "w") as f:
        f.write(timezone.now().isoformat())


# --------------------------------------------------------------------------- #
# Database facts
# --------------------------------------------------------------------------- #
def _db_path():
    return settings.DATABASES["default"]["NAME"]


def db_size_bytes():
    try:
        return os.path.getsize(_db_path())
    except OSError:
        return 0


def free_disk_bytes(path=None):
    try:
        return shutil.disk_usage(path or os.path.dirname(_db_path()) or ".").free
    except OSError:
        return 0


def db_stats():
    """Read-only snapshot for the health endpoint. Never writes."""
    now = timezone.now()
    with connection.cursor() as c:
        c.execute("PRAGMA page_size")
        page_size = c.fetchone()[0]
        c.execute("PRAGMA page_count")
        page_count = c.fetchone()[0]
        c.execute("PRAGMA freelist_count")
        free_pages = c.fetchone()[0]

    expired = Session.objects.filter(expire_date__lt=now).count()
    live = Session.objects.filter(expire_date__gte=now).count()

    device_rows = ActiveDevice.objects.count()
    online_cutoff = now - datetime.timedelta(seconds=_DEVICE_ONLINE_SECONDS)
    devices_online = ActiveDevice.objects.filter(last_seen__gte=online_cutoff).count()
    prune_cutoff = now - datetime.timedelta(days=DEVICE_RETENTION_DAYS)
    devices_prunable = ActiveDevice.objects.filter(last_seen__lt=prune_cutoff).count()

    return {
        "db_bytes": db_size_bytes(),
        "db_mb": round(db_size_bytes() / 1048576.0, 2),
        "page_size": page_size,
        "page_count": page_count,
        "free_pages": free_pages,
        "reclaimable_mb": round(free_pages * page_size / 1048576.0, 2),
        "sessions_expired": expired,
        "sessions_live": live,
        "device_rows": device_rows,
        "devices_online": devices_online,
        "devices_prunable": devices_prunable,
        "free_disk_mb": round(free_disk_bytes() / 1048576.0, 1),
        "backups": backup_count(),
        "latest_backup": _iso(latest_backup_time()),
        "last_cleanup": _iso(last_run("cleanup")),
        "last_backup_run": _iso(last_run("backup")),
    }


def _iso(dt):
    return dt.isoformat() if dt else None


# --------------------------------------------------------------------------- #
# Backup — VACUUM INTO
# --------------------------------------------------------------------------- #
# VACUUM INTO writes an already-compacted copy without holding the write lock the way an
# in-place VACUUM does, so it is safe to run while the app is serving.
BACKUP_GLOB = "gstbillingdb-*.sqlite3"


def _backup_dir():
    d = getattr(settings, "DB_BACKUP_DIR", None) or os.path.join(settings.BASE_DIR, "backups")
    os.makedirs(d, exist_ok=True)
    return d


def backup_files():
    """Existing backups, newest first."""
    files = glob.glob(os.path.join(_backup_dir(), BACKUP_GLOB))
    return sorted(files, key=os.path.getmtime, reverse=True)


def backup_count():
    return len(backup_files())


def latest_backup_time():
    files = backup_files()
    if not files:
        return None
    return timezone.make_aware(
        datetime.datetime.fromtimestamp(os.path.getmtime(files[0])),
        timezone.get_default_timezone())


def run_backup(keep=None):
    """Write a compacted copy to DB_BACKUP_DIR and prune to the newest `keep`.

    Skips (without erroring) when free disk is too tight — backups must never be the
    thing that fills the server.
    """
    keep = keep if keep is not None else getattr(settings, "DB_BACKUP_KEEP", 7)
    size = db_size_bytes()
    free = free_disk_bytes()
    # Need room for this copy plus a safety margin; a same-day rerun overwrites, so the
    # requirement doesn't grow with retention.
    needed = size * 2 + 32 * 1048576
    if free < needed:
        return {
            "ok": False,
            "skipped": "low_disk",
            "free_disk_mb": round(free / 1048576.0, 1),
            "needed_mb": round(needed / 1048576.0, 1),
        }

    name = "gstbillingdb-%s.sqlite3" % timezone.localtime().strftime("%Y-%m-%d")
    dest = os.path.join(_backup_dir(), name)
    # VACUUM INTO refuses to overwrite, so clear a same-day rerun first.
    if os.path.exists(dest):
        os.unlink(dest)

    with connection.cursor() as c:
        # Parameters aren't allowed in VACUUM INTO; the path is ours, not user input,
        # and the quote-doubling keeps a stray apostrophe in a directory name safe.
        c.execute("VACUUM INTO '%s'" % dest.replace("'", "''"))

    pruned = []
    for old in backup_files()[keep:]:
        try:
            os.unlink(old)
            pruned.append(os.path.basename(old))
        except OSError:
            pass

    _mark_run("backup")
    return {
        "ok": True,
        "backup": name,
        "backup_mb": round(os.path.getsize(dest) / 1048576.0, 2),
        "kept": min(backup_count(), keep),
        "pruned": pruned,
        "free_disk_mb": round(free_disk_bytes() / 1048576.0, 1),
    }


# --------------------------------------------------------------------------- #
# Stale quotation retention
# --------------------------------------------------------------------------- #
# A quotation is a short-lived working document, so EVERY status is purged once it is old
# enough — DRAFT, PENDING, APPROVED and CONVERTED alike, desktop or mobile cart. This is a
# deliberate owner decision; the notes below are what it costs, not arguments against it.
#
#   * The permanent record is the INVOICE, plus the customer ledger and stock logs. None of
#     those are touched here, so nothing financial is lost by dropping a quotation.
#   * Nothing in the schema points AT a Quotation, so a delete cascades nowhere. Removing a
#     row whose converted_invoice is set does NOT touch that invoice.
#   * The customer's mobile order list (/m/c/orders) is built from these rows, so it becomes
#     a rolling window: an order shows as "Invoiced" when billed, then ages out.
#   * "Delete invoice -> restore the source quotation as DRAFT" degrades gracefully. With the
#     original gone, invoice_delete / invoice_to_quotation fall through to
#     _quotation_from_invoice() and build a fresh quotation from the invoice instead. The
#     feature keeps working; it just no longer resurrects the original number and notes.
#
# Retention is the ONLY thing keeping a quotation alive, which is why the floor below exists.
ALL_STATUSES_PURGED = True

# Refuse a retention window shorter than this. Now that no status is spared, a fat-fingered
# `?quotations=1` would delete work someone is in the middle of.
MIN_QUOTATION_RETENTION_DAYS = 7


def stale_quotations(days):
    """The quotations a purge at `days` would remove. Shared by the preview and the delete
    so what you are shown is exactly what goes."""
    cutoff_date = (timezone.localtime() - datetime.timedelta(days=days)).date()
    cutoff_dt = timezone.now() - datetime.timedelta(days=days)
    # Every status, linked or not. Age is the only test — but both clocks must agree it is
    # old: quotation_date can be back-dated by hand, and updated_at proves nobody has
    # touched it since. A quotation edited today survives however old its date.
    return (Quotation.objects
            .filter(quotation_date__lt=cutoff_date)
            .filter(Q(updated_at__lt=cutoff_dt) | Q(updated_at__isnull=True)))


def purge_quotations(days, commit=True):
    """Delete EVERY quotation older than `days`, whatever its status. Returns what it did
    (or would do with commit=False).

    Nothing references a Quotation, so this cascades nowhere — invoices, ledger entries and
    stock logs are all untouched. See the notes above for what a purge gives up.
    """
    days = int(days)
    if days < MIN_QUOTATION_RETENTION_DAYS:
        return {"ok": False, "skipped": "retention_too_short",
                "requested_days": days, "minimum_days": MIN_QUOTATION_RETENTION_DAYS}

    qs = stale_quotations(days)
    # Record what goes, so the response is an audit trail and not just a count.
    doomed = list(qs.values_list("id", "quotation_number", "status", "quotation_date"))
    by_status = {}
    linked = 0
    for _, _, status, _ in doomed:
        by_status[status] = by_status.get(status, 0) + 1
    linked = qs.filter(converted_invoice__isnull=False).count()

    if commit and doomed:
        qs.delete()

    # After a commit the rows are already gone, so the live count IS what was kept; in a
    # dry-run nothing was removed, so subtract what would have been.
    remaining = Quotation.objects.count()

    return {
        "ok": True,
        "days": days,
        "deleted": len(doomed) if commit else 0,
        "would_delete": len(doomed),
        "by_status": by_status,
        # How many carried an invoice link. Their invoices are untouched; this is only
        # here so the nightly response says plainly that linked rows went too.
        "had_invoice_link": linked,
        "numbers": [n for _, n, _, _ in doomed][:50],
        "kept": remaining if commit else remaining - len(doomed),
    }


# --------------------------------------------------------------------------- #
# Stale presence rows (active-device heartbeat)
# --------------------------------------------------------------------------- #
# Device rows are KEPT as history (so the profile shows each device's last-seen and a
# returning browser is recognised), not deleted on logout. This sweep only removes rows
# that have been idle for a long time, so the table stays bounded without losing the
# recent device history. Nothing here affects the live online count (75s window).
DEVICE_RETENTION_DAYS = 90
# "Online" proxy for the health snapshot only (the real window lives in views/presence).
_DEVICE_ONLINE_SECONDS = 120


def purge_stale_devices(days=DEVICE_RETENTION_DAYS):
    """Delete ActiveDevice rows not seen in `days`. Returns how many went."""
    cutoff = timezone.now() - datetime.timedelta(days=days)
    deleted, _ = ActiveDevice.objects.filter(last_seen__lt=cutoff).delete()
    return deleted


# --------------------------------------------------------------------------- #
# Cleanup
# --------------------------------------------------------------------------- #
# An in-place VACUUM needs roughly 2x the file size free while it runs. It is atomic —
# a crash rolls back and leaves the original intact — so the guard here is about disk,
# not corruption.
VACUUM_HEADROOM = 2.5

# Don't rewrite the whole file to win back a trivial amount. This is what makes a DAILY
# vacuum sensible: on most nights only a few expired sessions were freed, so the run skips
# and costs nothing, and it only actually compacts once the free space is worth the write.
VACUUM_MIN_RECLAIM_MB = 0.5


def reclaimable_bytes():
    """Free (unused) space sitting inside the file, which a VACUUM would give back."""
    with connection.cursor() as c:
        c.execute("PRAGMA page_size")
        page_size = c.fetchone()[0]
        c.execute("PRAGMA freelist_count")
        free_pages = c.fetchone()[0]
    return free_pages * page_size


def run_cleanup(vacuum=False, quotation_days=None):
    """Delete expired sessions and stale presence rows; optionally purge stale
    quotations, then compact.

    Sessions and stale ActiveDevice rows always. Quotations ONLY when `quotation_days`
    is given — never by default. Nothing else in this database is touched.
    """
    now = timezone.now()
    before = db_size_bytes()
    stats = {"db_mb_before": round(before / 1048576.0, 2)}

    # Sessions are the only table that grows without bound and holds nothing of value
    # once expired. Django ships `clearsessions` for exactly this; doing it inline keeps
    # the cron endpoint to a single code path.
    deleted, _ = Session.objects.filter(expire_date__lt=now).delete()
    stats["expired_sessions"] = deleted
    stats["sessions_live"] = Session.objects.filter(expire_date__gte=now).count()

    # Device rows are kept as history; only long-idle ones (DEVICE_RETENTION_DAYS) are
    # pruned so the table stays bounded without losing the recent device list.
    stats["pruned_devices"] = purge_stale_devices()
    stats["device_rows"] = ActiveDevice.objects.count()

    # Opt-in retention. Runs before the vacuum so the freed pages are reclaimed in the
    # same pass.
    if quotation_days is not None:
        stats["quotations"] = purge_quotations(quotation_days)

    if vacuum:
        stats.update(_maybe_vacuum(before))

    stats["db_mb_after"] = round(db_size_bytes() / 1048576.0, 2)
    stats["freed_mb"] = round((before - db_size_bytes()) / 1048576.0, 2)
    _mark_run("cleanup")
    return stats


def _maybe_vacuum(size):
    """Compact in place — but only when it is worth doing, a recent backup exists, and
    there is enough disk."""
    floor_mb = getattr(settings, "DB_VACUUM_MIN_RECLAIM_MB", VACUUM_MIN_RECLAIM_MB)
    reclaim = reclaimable_bytes()
    if reclaim < floor_mb * 1048576:
        # Nothing worth a full-file rewrite. Reported, not silent, so a daily run still
        # tells you why it did nothing.
        return {"vacuum": "skipped", "vacuum_reason": "nothing_to_reclaim",
                "reclaimable_mb": round(reclaim / 1048576.0, 2)}

    latest = latest_backup_time()
    if latest is None or (timezone.now() - latest) > datetime.timedelta(hours=48):
        # The vacuum itself is safe, but rewriting the whole file with no recent restore
        # point on disk is a bet we don't need to take — the backup job runs daily.
        return {"vacuum": "skipped", "vacuum_reason": "no_recent_backup",
                "latest_backup": _iso(latest)}

    free = free_disk_bytes()
    if free < size * VACUUM_HEADROOM:
        return {"vacuum": "skipped", "vacuum_reason": "low_disk",
                "free_disk_mb": round(free / 1048576.0, 1)}

    # Must run outside a transaction. ATOMIC_REQUESTS is off and management commands are
    # in autocommit, so this is fine from both entry points.
    with connection.cursor() as c:
        c.execute("VACUUM")
    return {"vacuum": "done"}
