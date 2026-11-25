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
    every 10 min    GET /cron/syncup?key=...        (once SyncUp logins are issued)

Single job, if you only get one entry — does everything, in the right order:
    02:00 daily     GET /cron/cleanup?key=...&backup=1&vacuum=1&quotations=15

Do NOT schedule `cleanup?vacuum=1` alone: the vacuum requires a backup from the last 48h,
so with nothing ever writing one it would quietly stop compacting after two days while
still reporting success. Add &backup=1 (above) or schedule /cron/backup alongside it.
"""
import hmac
import logging
from functools import wraps

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import telegram_backup
from .cleanup import LockBusy, db_stats, job_lock, run_backup, run_cleanup

log = logging.getLogger(__name__)


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


class AfterReply(JsonResponse):
    """A reply that does one more job once it has been sent.

    PythonAnywhere runs web apps without --enable-threads, so a background thread is not
    available to us. A WSGI server calls close() on the response after the body has gone to
    the client, which gives us the one safe place to do slow work without the caller waiting
    on it — here, pushing a 7 MB database to Telegram while the cron service has already had
    its 200. Django's test client calls close() too, so tests exercise the same path.

    Worst case on a server that buffers the whole reply, the call simply takes as long as the
    upload; it still works, it just isn't quick."""

    def __init__(self, data, then=None, **kwargs):
        super().__init__(data, **kwargs)
        self._then = then

    def close(self):
        super().close()
        if self._then is None:
            return
        try:
            self._then()
        except Exception:                           # noqa: BLE001 — the reply has already gone
            log.exception("after-reply work failed")


# --------------------------------------------------------------------------- #
# Backup — call this once a day, BEFORE cleanup
# --------------------------------------------------------------------------- #
@cron_endpoint
def backup(request):
    """Write a compacted copy via VACUUM INTO and prune to the retention in force — seven
    copies normally, two once the nightly file also goes to Telegram.

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
            out = run_backup(keep=keep)
    except LockBusy:
        return _locked("backup")
    except Exception as e:  # noqa: BLE001
        return _failed(e)

    # The copy is on disk and the cron has its answer. Sending it to Telegram happens after
    # this reply, so a slow upload can't make the schedule look like a failure.
    if not telegram_backup.enabled():
        out["telegram"] = "off"
        return JsonResponse(out)
    out["telegram"] = "sending after this reply"
    return AfterReply(out, then=telegram_backup.run_daily)


# --------------------------------------------------------------------------- #
# Cleanup — call this once a day; add &vacuum=1 weekly, off-peak
# --------------------------------------------------------------------------- #
@cron_endpoint
def cleanup(request):
    """Delete expired sessions and spent outbox messages, and optionally back up and
    compact in the same call.

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

    Spent outbox rows are pruned here rather than by /cron/syncup, which runs every few
    minutes and should only send: login records go after 3 days (the person's own count and
    last-opened survive them), Telegram reports after a week (each carries its whole text, and
    SyncUp keeps its own copy), everything else after a fortnight. See cleanup.purge_outbox().

    The vacuum is still skipped when there is too little to reclaim, no recent backup, or
    too little free disk — it reports which, rather than failing.
    """
    try:
        with job_lock("cleanup"):
            out = {"ok": True}
            took_backup = _truthy(request.GET.get("backup"))
            if took_backup:
                out["backup_run"] = _backup_guarded()
            out.update(run_cleanup(
                vacuum=_truthy(request.GET.get("vacuum")),
                quotation_days=_int_param(request, "quotations")))
        # Outside the lock and after the reply: the upload is not cleanup's business and the
        # cron service shouldn't hold a lock, or a connection, while it happens.
        if not (took_backup and telegram_backup.enabled()):
            out["telegram"] = "off" if took_backup else "not asked for"
            return JsonResponse(out)
        out["telegram"] = "sending after this reply"
        return AfterReply(out, then=telegram_backup.run_daily)
    except LockBusy:
        return _locked("cleanup")
    except Exception as e:  # noqa: BLE001
        return _failed(e)


# --------------------------------------------------------------------------- #
# SyncUp — every 5-15 minutes, once app logins are issued
# --------------------------------------------------------------------------- #
@cron_endpoint
def syncup(request):
    """Re-send any app login whose SyncUp state fell behind - a push that
    failed or hit its short time limit while a business was changing access. Logins already
    in step cost no network call, so a frequent schedule is cheap.

    Also sends SyncUp messages: queues the scheduled ones that are due (morning list, evening
    summary, weekly overdue, tile subtitles), sends the outbox, and looks up Approve / Reject
    answers whose callback never arrived. Telegram reports whose time has come are queued in
    the same run (see telegram_reports.py)."""
    from . import appusers, syncup_messages, telegram_reports
    from .syncup_client import is_configured
    if not is_configured():
        return JsonResponse({"ok": True, "skipped": "not_configured"})
    try:
        with job_lock("syncup"):
            out = {"ok": True, "logins": appusers.retry_pending()}
            scheduled = syncup_messages.run_schedules()
            # Telegram reports are queued first, so anything due goes out in this same run.
            out["telegram"] = telegram_reports.run_due()
            out["messages"] = {"scheduled": scheduled, **syncup_messages.flush(),
                               "answers": syncup_messages.reconcile()}
            return JsonResponse(out)
    except LockBusy:
        return _locked("syncup")
    except Exception as e:  # noqa: BLE001
        return _failed(e)
