"""The Telegram button on a report page (Overdue, Cheque leafs, Collection calendar).

The business chooses WHICH of its reports go to Telegram and WHEN. It never sees or types a
chat id: a platform admin enables Telegram for the business and adds its groups on the console
(see views/console.py), and this popup only picks among those.

Both views answer JSON — the popup is a small piece of script on the page it belongs to.
"""
import datetime
import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .. import telegram_reports as tg
from ..models import TelegramChat, TelegramReport

MAX_ROWS = 6            # per report — more than enough for "90 days at 9:00, 120 at 9:05"


def _known(report):
    return report in tg.REPORTS


def _row_json(row):
    return {
        "id": row.id,
        "enabled": row.enabled,
        "send_at": row.send_at.strftime("%H:%M"),
        "days": row.days or None,
        "chats": [c.id for c in row.chats.all()],
        "last": _last_words(row),
    }


def _last_words(row):
    if not row.last_sent_on:
        return "Not sent yet."
    return "Last run %s — %s" % (row.last_sent_on.strftime("%d %b %Y"),
                                 row.last_status or "queued")


def _state(request, report):
    business = request.user
    meta = tg.REPORTS[report]
    chats = tg.chats(business)
    enabled = tg.business_enabled(business)
    if not tg.relay_ready():
        reason = "Telegram reports are switched off for the platform right now."
    elif not enabled:
        reason = ("Telegram isn't switched on for this business yet. Ask us to switch it on and "
                  "add your group.")
    elif not chats:
        reason = "No Telegram group has been added for this business yet — ask us to add one."
    else:
        reason = ""
    return {
        "ok": True,
        "available": not reason,
        "reason": reason,
        "label": meta["label"],
        "has_days": meta["has_days"],
        "day_options": tg.DAY_OPTIONS if meta["has_days"] else [],
        "default_time": meta["default_time"].strftime("%H:%M"),
        "default_days": meta["default_days"],
        "chats": [{"id": c.id, "name": c.name} for c in chats],
        "rows": [_row_json(r) for r in TelegramReport.objects.filter(
            business=business, report=report).prefetch_related("chats")],
    }


def _clean_rows(request, report, payload):
    """(rows, error) — each row checked before anything is written."""
    meta = tg.REPORTS[report]
    mine = {c.id: c for c in TelegramChat.objects.filter(business=request.user)}
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return None, "Nothing to save."
    if len(rows) > MAX_ROWS:
        return None, "That's more times than one report can have (%d)." % MAX_ROWS
    cleaned = []
    for raw in rows:
        if not isinstance(raw, dict):
            return None, "Nothing to save."
        try:
            send_at = datetime.datetime.strptime((raw.get("send_at") or "").strip(), "%H:%M").time()
        except ValueError:
            return None, "Give each time as HH:MM."
        params = {}
        if meta["has_days"]:
            try:
                days = int(raw.get("days") or meta["default_days"])
            except (TypeError, ValueError):
                return None, "Pick how many days overdue."
            if days not in tg.DAY_OPTIONS:
                return None, "That isn't one of the overdue day options."
            params = {"days": days}
        # A chat id that isn't this business's is simply not ours to send to.
        chat_ids = [i for i in (raw.get("chats") or []) if i in mine]
        cleaned.append({"enabled": bool(raw.get("enabled", True)), "send_at": send_at,
                        "params": params, "chats": chat_ids})
    return cleaned, None


@login_required
def report_settings(request, report):
    """GET the popup's state; POST replaces this report's schedule for this business."""
    if not _known(report):
        return JsonResponse({"ok": False, "message": "Unknown report."}, status=404)
    if request.method != "POST":
        return JsonResponse(_state(request, report))
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "message": "Bad request."}, status=400)
    rows, error = _clean_rows(request, report, payload)
    if error:
        return JsonResponse({"ok": False, "message": error}, status=400)

    existing = list(TelegramReport.objects.filter(business=request.user, report=report))
    keep = []
    for i, row in enumerate(rows):
        # Reuse a row where we can, so "last run" survives an edit.
        obj = existing[i] if i < len(existing) else TelegramReport(business=request.user,
                                                                  report=report)
        obj.enabled, obj.send_at, obj.params = row["enabled"], row["send_at"], row["params"]
        obj.save()
        obj.chats.set(row["chats"])
        keep.append(obj.pk)
    TelegramReport.objects.filter(business=request.user, report=report).exclude(
        pk__in=keep).delete()
    return JsonResponse(dict(_state(request, report), saved=True))


@login_required
@require_POST
def report_send_now(request, report):
    """Send this report to the chosen groups straight away."""
    if not _known(report):
        return JsonResponse({"ok": False, "message": "Unknown report."}, status=404)
    if not tg.available(request.user):
        return JsonResponse({"ok": False, "message": "Telegram isn't set up for this business."},
                            status=400)
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        payload = {}
    params = {}
    if tg.REPORTS[report]["has_days"]:
        try:
            days = int(payload.get("days") or tg.REPORTS[report]["default_days"])
        except (TypeError, ValueError):
            days = tg.REPORTS[report]["default_days"]
        params = {"days": days}
    picked = [i for i in (payload.get("chats") or []) if isinstance(i, int)]
    chats = [c for c in tg.chats(request.user) if not picked or c.id in picked]
    if not chats:
        return JsonResponse({"ok": False, "message": "Pick at least one group."}, status=400)
    queued, count = tg.send_now(request.user, report, params, chats)
    if not queued:
        return JsonResponse({"ok": False, "message": "Nothing was sent — try again in a moment."})
    return JsonResponse({"ok": True, "message": "Sent to %d group%s (%d row%s in the report)."
                         % (len(chats), "" if len(chats) == 1 else "s",
                            count, "" if count == 1 else "s")})
