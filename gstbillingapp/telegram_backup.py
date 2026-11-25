"""Sending the daily database backup to Telegram.

The backup itself already exists: `/cron/backup` writes a compacted copy with `VACUUM INTO`
and keeps the last seven (cleanup.py). All this adds is getting one off the server, because a
backup that only lives on the machine it came from is not a backup of that machine.

Three things worth knowing about how it runs here:

  * **It rides the daily cron, not a new one.** /cron/backup takes the copy; the send happens
    after that request has already answered (see `AfterReply` in cron_views), so the cron
    service never waits on a 7 MB upload and never times out because of one.
  * **It has no bot of its own.** GSTSync reaches Telegram through SyncUp's relay, the same
    way every report and alert does, so the token and the send log stay in one place.
  * **Once a day.** A file lock held for 20 hours after a good send, released after a failed
    one, so the next cron run retries rather than waiting a day.

The whole database goes into that chat: every business's customers, ledgers and invoices,
along with password hashes and the SyncUp key. That is the point — it has to be restorable —
but it is why the console asks for a chat id explicitly and says so in plain words.
"""
import logging
import os

from django.conf import settings
from django.utils import timezone

from . import syncup_client
from .cleanup import LockBusy, job_lock
from .models import SyncUpSettings

log = logging.getLogger(__name__)

# Held after a good send, so the next cron call today does nothing. Twenty hours rather than
# twenty-four: a cron that drifts an hour later each day would otherwise skip one.
LOCK = "telegram_backup"
LOCK_TTL = 20 * 3600


def chat_id():
    """Where backups go, or "" when nobody has chosen a chat."""
    return (SyncUpSettings.load().backup_chat_id or "").strip()


def enabled():
    return bool(chat_id()) and syncup_client.config().is_configured


def retention():
    """How many copies to keep on the server.

    Seven while this is the only copy there is. Two once each night's file also reaches
    Telegram: the history lives off the server from then on, and the disk here is small
    enough that seven copies of a growing database is most of it. Two is enough to undo
    today — yesterday's file is still on the machine when today's is written."""
    if enabled():
        return getattr(settings, "DB_BACKUP_KEEP_OFFSITE", 2)
    return getattr(settings, "DB_BACKUP_KEEP", 7)


def latest_file():
    """The newest backup on disk, or None. Sent as it is — a copy that has been opened and
    rewritten is a copy that might differ from the one restored."""
    folder = getattr(settings, "DB_BACKUP_DIR", "")
    if not folder or not os.path.isdir(folder):
        return None
    found = [os.path.join(folder, n) for n in os.listdir(folder) if n.endswith(".sqlite3")]
    return max(found, key=os.path.getmtime) if found else None


def _rows():
    """A few counts for the note — enough to tell at a glance that the file isn't empty."""
    from .models import Customer, Invoice, User
    try:
        return "%d businesses, %d customers, %d invoices" % (
            User.objects.count(), Customer.objects.count(), Invoice.objects.count())
    except Exception:                               # noqa: BLE001 — a note must not fail a send
        return ""


def note(path):
    """What goes with the file. Plain text: the caption is read on a phone, and it has to say
    what this is, when it was taken, and what to do with it."""
    name = os.path.basename(path)
    size = os.path.getsize(path)
    when = timezone.localtime().strftime("%d %b %Y, %H:%M")
    lines = [
        "GSTSync database backup",
        "%s · %s" % (when, getattr(settings, "SITE_HOST", "") or "gstsync"),
        "%s, %.1f MB" % (name, size / 1048576.0),
    ]
    counts = _rows()
    if counts:
        lines.append(counts)
    lines.append("")
    lines.append("To restore: stop the web app, put this file in place of "
                 "gstbillingdb.sqlite3, then Reload.")
    return "\n".join(lines)


def _send_file(path=None):
    """(ok, message, settled) — the send, and whether today's attempt is finished with.

    `settled` is the part worth explaining. A timeout is not a failure we may simply repeat:
    SyncUp carries on uploading after we stop waiting, so trying again would put a second
    copy of the database in the chat. A timeout therefore counts as settled — the day is
    done, the error is recorded, and the next run is tomorrow's."""
    cfg = SyncUpSettings.load()
    where = (cfg.backup_chat_id or "").strip()
    if not where:
        return False, "No Telegram chat chosen for backups.", True
    path = path or latest_file()
    if not path or not os.path.exists(path):
        return False, "No backup file on disk yet — /cron/backup takes one daily.", False
    try:
        # The path, not the bytes: the client streams it from disk, so a database that has
        # grown past comfortable never has to sit whole in a web worker's memory.
        syncup_client.telegram_document(where, os.path.basename(path), path, note(path))
    except syncup_client.SyncUpError as e:
        log.warning("Backup to Telegram failed: %s", e)
        SyncUpSettings.objects.filter(pk=cfg.pk).update(backup_last_error=str(e)[:300])
        return False, str(e), bool(getattr(e, "timed_out", False))
    except OSError as e:
        log.warning("Backup file unreadable: %s", e)
        return False, "Could not read %s: %s" % (os.path.basename(path), e), False
    SyncUpSettings.objects.filter(pk=cfg.pk).update(
        backup_last_sent_at=timezone.now(), backup_last_error="")
    log.info("Backup %s sent to Telegram", os.path.basename(path))
    return True, "Sent %s." % os.path.basename(path), True


def send(path=None):
    """Send one backup now. Returns (ok, message) — for the console's button, where somebody
    is waiting for an answer."""
    ok, message, _settled = _send_file(path)
    return ok, message


def run_daily():
    """For the cron, after its reply. Takes the lock, sends, and keeps the lock only if it
    worked — a failure leaves the way clear for the next run to try again.

    Returns a word for the cron's JSON: "off", "sent today", "sent", or the failure."""
    if not enabled():
        return "off"
    try:
        lock = job_lock(LOCK, LOCK_TTL)
        lock.__enter__()
    except LockBusy:
        return "sent today"
    ok, message, settled = _send_file()
    if not ok and not settled:
        lock.__exit__(None, None, None)             # let the next run have another go
        return message
    # Sent, or stopped waiting on one that may yet arrive. Either way the lock stays and
    # today is done — a second attempt risks a second copy of the database in the chat.
    return "sent" if ok else message


def status():
    """What the console shows: where it goes, when it last worked, what went wrong."""
    cfg = SyncUpSettings.load()
    path = latest_file()
    return {
        "chat_id": (cfg.backup_chat_id or "").strip(),
        "label": cfg.backup_chat_label,
        "enabled": enabled(),
        "last_sent_at": cfg.backup_last_sent_at,
        "last_error": cfg.backup_last_error,
        "file": os.path.basename(path) if path else "",
        "size_mb": round(os.path.getsize(path) / 1048576.0, 1) if path else 0,
        "keep": getattr(settings, "DB_BACKUP_KEEP_OFFSITE", 2),
        "on_disk": len(_backup_files()),
    }


def _backup_files():
    folder = getattr(settings, "DB_BACKUP_DIR", "")
    if not folder or not os.path.isdir(folder):
        return []
    return [n for n in os.listdir(folder) if n.endswith(".sqlite3")]
