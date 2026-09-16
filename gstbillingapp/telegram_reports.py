"""Telegram reports — the three daily reports a business sends to its own Telegram group(s).

  * A platform admin switches Telegram on for a business and adds its chat ids (console only —
    an id is never typed on the business side). The business then opens a report's own page
    (Overdue, Cheque leafs, Collection calendar), presses **Telegram**, and sets when it goes.
  * Sending goes through SyncUp's relay (`telegram/bulk`), using the same outbox and the same
    /cron/syncup run as the app's SyncUp messages — so no page ever waits on Telegram.
  * The text is exactly what the old SyncUp-side job posted: the same MarkdownV2 blocks, built
    here now instead of behind three open, unauthenticated API endpoints.
"""
import datetime
import logging

from django.utils import timezone

from . import syncup_client
from .models import (Book, BookLog, BusinessTelegram, ChequeLeaf, Customer, SyncUpMessage,
                     SyncUpSettings, TelegramChat, TelegramReport, UserProfile)
from .templatetags.money import format_inr_smart
from .utils import _escape_md

log = logging.getLogger(__name__)

# Telegram's hard cap is 4096 characters; leave room for the "Part 1 of 2" line.
MAX_TEXT = 3900
# A report the cron missed (the site was down) still goes out within this long after its time —
# after that it waits for tomorrow, so nothing meant for 3 a.m. lands at breakfast.
CATCH_UP = datetime.timedelta(hours=2)
# Schedules looked at per cron run, so one long list can't hold up everything else.
PER_RUN = 30

SEPARATOR = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
IGNORE_SMALL_OVERDUE = 10.0        # rupees — ignore a sub-₹10 overdue remainder
DAY_OPTIONS = list(range(15, 465, 15))


# --------------------------------------------------------------------------- #
# The reports — same MarkdownV2 the group receives today
# --------------------------------------------------------------------------- #
def _footer(lines, today):
    lines.append("🦀  _Crab AI \\| %s_" % _escape_md(today.strftime("%d %b %Y")))


def overdue_markdown(business, days=90):
    """Customers overdue by `days`+ — FIFO, oldest purchase first, ignoring sub-₹10 remainders.
    Returns (markdown, how many customers)."""
    today = datetime.date.today()
    days = days if days in DAY_OPTIONS else 90
    profile = UserProfile.objects.filter(user=business).first()
    rows, total_overdue = [], 0.0

    for book in Book.objects.filter(user=business).select_related("customer"):
        if not book.customer:
            continue
        logs = list(BookLog.objects.filter(parent_book=book, is_active=True).order_by("date"))
        purchased = sum(abs(lg.change) for lg in logs if lg.change_type == 1)
        # Signed, not abs: Paid/Returned are positive, but a negative "Other" is a CHARGE —
        # abs() would wrongly treat it as a settlement (same rule as the ledger's own balance).
        settled = sum(lg.change for lg in logs if lg.change_type in (0, 2, 3))
        if purchased - settled <= 0.01:
            continue
        entries = sorted(({"amount": abs(lg.change), "age": max((today - lg.date.date()).days, 0)}
                          for lg in logs if lg.change_type == 1 and lg.date),
                         key=lambda e: e["age"], reverse=True)
        remaining, overdue = settled, 0.0
        for entry in entries:
            if remaining >= entry["amount"]:
                remaining -= entry["amount"]
                continue
            unpaid = entry["amount"] - remaining if remaining > 0 else entry["amount"]
            remaining = 0
            if entry["age"] >= days:
                overdue += unpaid
        if overdue < IGNORE_SMALL_OVERDUE:
            continue
        total_overdue += overdue
        rows.append({"name": book.customer.customer_name,
                     "phone": book.customer.customer_phone or "",
                     "amount": round(overdue, 2)})
    rows.sort(key=lambda r: r["amount"], reverse=True)

    total_str = _escape_md(format_inr_smart(round(total_overdue, 2)))
    title = (profile.business_title if profile else "") or business.username
    lines = ["📋  *OVERDUE REPORT*",
             "📅  %s \\| ⏳ %d Days" % (_escape_md(today.strftime("%d %b %Y")), days), "",
             SEPARATOR, "🏢  *%s*" % _escape_md(title)]
    if profile and profile.business_phone:
        lines.append("📞  %s" % _escape_md(profile.business_phone))
    if profile and profile.business_gst:
        lines.append("🔖  %s" % _escape_md(profile.business_gst))
    if profile and profile.business_brand:
        lines.append("🏷️  %s" % _escape_md(profile.business_brand))
    lines.append("👥  Total Customers: *%d*" % Customer.objects.filter(user=business).count())
    lines.append("⚠️  Overdue Customers: *%d*" % len(rows))
    lines.append("💰  Total Overdue: *Rs\\.%s*" % total_str)
    lines.append(SEPARATOR)
    lines.append("")
    if rows:
        for idx, r in enumerate(rows, 1):
            lines.append("%s\\. *%s*" % (_escape_md(str(idx)), _escape_md(r["name"])))
            if r["phone"]:
                lines.append("    📞  *%s*" % _escape_md(r["phone"]))
            lines.append("    💰  *%s*" % _escape_md("Rs.%s" % format_inr_smart(r["amount"])))
            lines.append("")
    else:
        lines.append("✅ _No overdue customers_")
        lines.append("")
    lines.append(SEPARATOR)
    lines.append("💰  Total Overdue: *Rs\\.%s*" % total_str)
    lines.append("")
    _footer(lines, today)
    return "\n".join(lines), len(rows)


def cheque_markdown(business):
    """Cheques clearing tomorrow. Returns (markdown, count)."""
    tomorrow = timezone.localtime().date() + datetime.timedelta(days=1)
    cheques = list(ChequeLeaf.objects.filter(user=business, clearance_date=tomorrow,
                                             status__in=["ISSUED", "PRESENTED", "BOUNCED"]))
    markdown = "_*💰 Cheque Clearance Reminder*_\n\n"
    amounts = 0
    if not cheques:
        markdown += "_No upcoming cheque clearances for %s\\._" % _escape_md(
            tomorrow.strftime("%d-%m-%Y"))
        markdown += "\n%s\n" % SEPARATOR
    else:
        for cheque in cheques:
            brand = str(cheque.user if cheque.user else "N/A")
            amounts += int(cheque.amount)
            markdown += (
                "🔢  Cheque No: *`%s`*\n" % _escape_md(str(cheque.cheque_number))
                + "🏦  Bank: *%s*\n" % _escape_md(cheque.bank)
                + "👤  Payee: *%s*\n" % _escape_md(cheque.payee_name)
                + "💰  Amount: *₹%s*\n" % _escape_md(str(cheque.amount))
                + "📅  Clearance Date: *%s*\n" % _escape_md(
                    cheque.clearance_date.strftime("%d-%m-%Y"))
                + "📌  Status: *%s*\n" % _escape_md(cheque.status)
                + "🏷️  Brand: *%s*\n" % _escape_md(brand.upper())
                + "%s\n\n" % SEPARATOR
            )
    if len(cheques) > 1:
        markdown += "*%d Cheques \\= ₹%s*\n" % (len(cheques), _escape_md(str(amounts)))
    markdown += "🦀  _Crab AI \\| %s_" % _escape_md(timezone.localtime().strftime("%d %b %Y"))
    return markdown, len(cheques)


def collection_markdown(business):
    """Today's collection route. Returns (markdown, count)."""
    # Customer.DAYS runs Sunday=0 … Saturday=6; Python's weekday() is Monday=0 … Sunday=6.
    day = (timezone.localtime().weekday() + 1) % 7
    day_name = Customer.DAYS[day][1]
    books = list(Book.objects.filter(user=business, customer__collection_day=day)
                 .exclude(customer_id__isnull=True).select_related("customer")
                 .order_by("current_balance"))
    lines = ["📅  _*COLLECTION ROUTE* \\- *%s*_\n" % _escape_md(day_name)]
    if not books:
        lines.append("_No customers with collection day on %s\\._" % _escape_md(day_name))
    for counter, book in enumerate(books, 1):
        customer = book.customer
        balance = -round(book.current_balance or 0, 2)
        lines.append("%s\\. *%s*" % (_escape_md(str(counter)), _escape_md(customer.customer_name)))
        if customer.customer_place:
            lines.append("    📍  *%s*" % _escape_md(customer.customer_place))
        lines.append("    💰  *₹%s*\n" % _escape_md(str(balance)))
    lines.append(SEPARATOR)
    _footer(lines, timezone.localtime())
    return "\n".join(lines), len(books)


def _days(params):
    try:
        value = int((params or {}).get("days") or 90)
    except (TypeError, ValueError):
        value = 90
    return value if value in DAY_OPTIONS else 90


REPORTS = {
    TelegramReport.OVERDUE: {
        "label": "Overdue report", "page": "overdue_report", "has_days": True,
        "default_time": datetime.time(9, 0), "default_days": 90,
        "build": lambda business, params: overdue_markdown(business, _days(params)),
    },
    TelegramReport.CHEQUE: {
        "label": "Cheque clearance reminder", "page": "cheque_leafs", "has_days": False,
        "default_time": datetime.time(19, 0), "default_days": 0,
        "build": lambda business, params: cheque_markdown(business),
    },
    TelegramReport.COLLECTION: {
        "label": "Collection route", "page": "customers_collection_calendar", "has_days": False,
        "default_time": datetime.time(9, 0), "default_days": 0,
        "build": lambda business, params: collection_markdown(business),
    },
}


def build(report, business, params=None):
    """(markdown, count) for one report of one business."""
    return REPORTS[report]["build"](business, params or {})


def split_parts(text, limit=MAX_TEXT):
    """Telegram refuses a message over 4096 characters — and the whole report would be lost.
    Split on line boundaries and number the parts instead."""
    if len(text) <= limit:
        return [text]
    parts, current, size = [], [], 0
    for line in text.split("\n"):
        line_size = len(line) + 1
        if current and size + line_size > limit:
            parts.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += line_size
    if current:
        parts.append("\n".join(current))
    return ["%s\n\n_Part %d of %d_" % (part, i, len(parts)) for i, part in enumerate(parts, 1)]


# --------------------------------------------------------------------------- #
# Who may send, and where to
# --------------------------------------------------------------------------- #
def relay_ready(cfg=None):
    """The platform's master switch, plus a SyncUp to relay through."""
    cfg = cfg or SyncUpSettings.load()
    return bool(cfg.telegram_enabled and cfg.is_configured)


def business_enabled(business):
    row = BusinessTelegram.objects.filter(user=business).first()
    return bool(row and row.enabled)


def chats(business, active_only=True):
    qs = TelegramChat.objects.filter(business=business)
    return list(qs.filter(is_active=True) if active_only else qs)


def available(business, cfg=None):
    """Can this business send at all? (Master switch, its own switch, one live chat id.)"""
    return relay_ready(cfg) and business_enabled(business) and bool(chats(business))


def chats_for(row):
    """The live chat ids one schedule goes to — every active id when none was picked."""
    picked = [c for c in row.chats.all() if c.is_active]
    return picked or chats(row.business)


# --------------------------------------------------------------------------- #
# Queueing and sending (through the SyncUp outbox and its cron)
# --------------------------------------------------------------------------- #
def queue_report(business, report, params=None, chat_rows=None, key=None, skip_empty=True):
    """Build the report and put it in the outbox, once per chat id (split if long).
    Returns (queued, count) — `queued` is 0 when there was nothing to report."""
    from .syncup_messages import queue
    text, count = build(report, business, params)
    if skip_empty and not count:
        return 0, 0
    targets = chat_rows if chat_rows is not None else chats(business)
    stamp = key or timezone.localtime().strftime("%Y%m%d%H%M%S")
    label = REPORTS[report]["label"]
    queued = 0
    for chat in targets:
        for index, part in enumerate(split_parts(text), 1):
            if queue(business=business, event=report, external_id=chat.chat_id,
                     kind=SyncUpMessage.KIND_TELEGRAM, title=label, text=part,
                     dedupe="tg:%s:%s:%s:%d" % (report, stamp, chat.chat_id, index),
                     any_time=True):
                queued += 1
    return queued, count


def run_due(now=None):
    """Queue every schedule whose time has come today. Called from /cron/syncup."""
    cfg = SyncUpSettings.load()
    if not relay_ready(cfg):
        return 0
    local = timezone.localtime(now or timezone.now())
    today, queued = local.date(), 0
    rows = (TelegramReport.objects.filter(enabled=True).select_related("business")
            .exclude(last_sent_on=today).order_by("send_at", "id")[:PER_RUN])
    for row in rows:
        due = timezone.localtime(
            timezone.make_aware(datetime.datetime.combine(today, row.send_at)))
        if local < due or due + CATCH_UP < local:
            continue                            # not yet, or too late — it waits for tomorrow
        if not available(row.business, cfg):
            continue
        sent, count = queue_report(row.business, row.report, row.params, chats_for(row),
                                   key="%s-%d" % (today.isoformat(), row.id))
        TelegramReport.objects.filter(pk=row.pk).update(
            last_sent_on=today,
            last_status=("Queued for %d chat(s)" % sent) if sent else "Nothing to report")
        queued += sent
    return queued


def send_now(business, report, params=None, chat_rows=None):
    """Send this report immediately (the popup's "Send now"). Returns (queued, count)."""
    from .syncup_messages import flush
    queued, count = queue_report(business, report, params, chat_rows,
                                 key="now-" + timezone.localtime().strftime("%Y%m%d%H%M%S"),
                                 skip_empty=False)
    if queued:
        flush(only_ids=list(SyncUpMessage.objects.filter(
            business=business, kind=SyncUpMessage.KIND_TELEGRAM, sent_at__isnull=True)
            .values_list("id", flat=True)))
    return queued, count


def test_message(chat):
    """Console: prove one chat id works. Sent inline — a console action may wait."""
    text = ("✅ *GSTSync test message*\n%s\nIf you can read this, reports will arrive here\\.\n%s"
            % (SEPARATOR, SEPARATOR))
    try:
        syncup_client.telegram_send(chat.chat_id, text)
    except syncup_client.SyncUpError as e:
        TelegramChat.objects.filter(pk=chat.pk).update(last_error=str(e)[:300])
        return False, str(e)
    TelegramChat.objects.filter(pk=chat.pk).update(last_ok_at=timezone.now(), last_error="")
    return True, "Test message delivered to %s." % chat.name
