"""HTTP-triggered maintenance endpoints — mounted at /cron/ (see gstbilling/urls.py).

An external cron service pings these on a schedule; there is no in-process scheduler.
They sit outside the session-authenticated site and carry their own shared-secret gate
(settings.CRON_KEY), so they are:

  * secret-gated — these are public URLs, and an unset key closes them rather than
                   opening them,
  * single-flight — a lockfile stops overlapping runs (see cleanup.job_lock),
  * idempotent   — safe to call twice; cron services retry on timeout,
  * quiet on overlap — a locked run answers 200, not 5xx, so a normal overlap does not
                   trip the cron service's alerting. Genuine failures do return 500.

Suggested schedule (Asia/Kolkata) — pick ONE of these two shapes.

Separate jobs, if your cron service allows several entries:
    02:00 daily     GET /cron/backup?key=...
    02:15 daily     GET /cron/cleanup?key=...
    02:30 Sundays   GET /cron/cleanup?key=...&vacuum=1
    09:00 daily     GET /cron/health?key=...        (optional, visibility only)

Single job, if you only get one entry — does everything, in the right order:
    02:00 daily     GET /cron/cleanup?key=...&backup=1&vacuum=1&quotations=15

Do NOT schedule `cleanup?vacuum=1` alone: the vacuum requires a backup from the last 48h,
so with nothing ever writing one it would quietly stop compacting after two days while
still reporting success. Add &backup=1 (above) or schedule /cron/backup alongside it.
"""
import hmac
from functools import wraps

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .cleanup import LockBusy, db_stats, job_lock, run_backup, run_cleanup


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def _authorized(request):
    expected = getattr(settings, "CRON_KEY", None)
    if not expected:
        return False  # unset key = endpoints closed, never open
    given = request.headers.get("X-Cron-Key") or request.GET.get("key", "")
    return hmac.compare_digest(str(given), str(expected))


def cron_endpoint(view):
    """Gate a view on the shared cron secret. GET and POST both allowed — plenty of cron
    services only issue GET."""

    @wraps(view)
    def inner(request, *args, **kwargs):
        if not _authorized(request):
            # 404 rather than 403: don't confirm the endpoint exists to anyone scanning.
            return HttpResponse(status=404)
        return view(request, *args, **kwargs)

    return csrf_exempt(require_http_methods(["GET", "POST"])(inner))


def _locked(job):
    """A previous run is still going. Normal operation, not a failure."""
    return JsonResponse({"ok": True, "skipped": "locked", "job": job})


def _backup_guarded(keep=None):
    """Run the backup under its own lock, so a combined call still can't collide with a
    separately-scheduled /cron/backup."""
    try:
        with job_lock("backup"):
            return run_backup(keep=keep)
    except LockBusy:
        return {"ok": True, "skipped": "locked"}


def _failed(e):
    return JsonResponse({"ok": False, "error": str(e)[:500]}, status=500)


def _truthy(v):
    return v in ("1", "true", "yes", "on")


def _int_param(request, name):
    """A positive integer query param, or None when absent/malformed — a typo must not
    silently become a destructive default."""
    raw = request.GET.get(name)
    if raw and raw.isdigit() and int(raw) > 0:
        return int(raw)
    return None


# --------------------------------------------------------------------------- #
# Health — call this first when wiring up the cron service
# --------------------------------------------------------------------------- #
@cron_endpoint
def health(request):
    """Read-only. Reports database size, reclaimable space, session counts, free disk and
    when each job last ran — so growth is visible rather than guessed at."""
    try:
        return JsonResponse({"ok": True, "now": timezone.now().isoformat(), **db_stats()})
    except Exception as e:  # noqa: BLE001 — surface any failure to the cron service as 5xx
        return _failed(e)


# --------------------------------------------------------------------------- #
# Backup — call this once a day, BEFORE cleanup
# --------------------------------------------------------------------------- #
@cron_endpoint
def backup(request):
    """Write a compacted copy via VACUUM INTO and prune to settings.DB_BACKUP_KEEP.

    Pass ?keep=N to override the retention for one call. Skips itself (reporting
    "low_disk", still 200) when free space is tight — a backup must never be the thing
    that fills the server.
    """
    try:
        keep = request.GET.get("keep")
        keep = int(keep) if keep and keep.isdigit() else None
    except (TypeError, ValueError):
        keep = None
    try:
        with job_lock("backup"):
            return JsonResponse(run_backup(keep=keep))
    except LockBusy:
        return _locked("backup")
    except Exception as e:  # noqa: BLE001
        return _failed(e)


# --------------------------------------------------------------------------- #
# Cleanup — call this once a day; add &vacuum=1 weekly, off-peak
# --------------------------------------------------------------------------- #
@cron_endpoint
def cleanup(request):
    """Delete expired sessions, and optionally back up and compact in the same call.

        ?backup=1        take a backup FIRST (same work as /cron/backup)
        ?quotations=15   delete ALL quotations older than 15 days (any status)
        ?vacuum=1        compact the file in place afterwards

    Passing all three makes this the single entry point a one-job cron service needs: the
    order is backup -> purge sessions -> purge quotations -> vacuum, so the vacuum's
    "needs a recent backup" guard is always satisfied by the backup this same call just
    took, and it reclaims everything the same pass freed.

    ?quotations is OPT-IN and deletes business records — every status, including CONVERTED
    and mobile cart orders — so read purge_quotations() for what that gives up. Invoices,
    ledger and stock are never touched. Omit it and no quotation is removed at all. Windows
    shorter than MIN_QUOTATION_RETENTION_DAYS are refused rather than honoured.

    The vacuum is still skipped when there is too little to reclaim, no recent backup, or
    too little free disk — it reports which, rather than failing.
    """
    try:
        with job_lock("cleanup"):
            out = {"ok": True}
            if _truthy(request.GET.get("backup")):
                out["backup_run"] = _backup_guarded()
            out.update(run_cleanup(
                vacuum=_truthy(request.GET.get("vacuum")),
                quotation_days=_int_param(request, "quotations")))
            return JsonResponse(out)
    except LockBusy:
        return _locked("cleanup")
    except Exception as e:  # noqa: BLE001
        return _failed(e)
