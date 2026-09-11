"""SyncUp messages — push notifications and Approve / Reject prompts to customers, staff and
admins (plan: md/SYNCUP_CONNECT_PLAN.md).

  * Nothing makes a business wait on SyncUp. An event only QUEUES a SyncUpMessage (after the
    save commits); /cron/syncup sends the queue, ≤25 per notify/bulk call. Approval prompts
    also get one immediate try, capped at QUICK_TIMEOUT.
  * Nothing is queued unless the console's master switch is on AND the business has switched
    that event on (console → business page). Everything starts off.
  * Only the right people: customers with an active login whose row the business shows in
    the app; staff and admins with an active staff login at that business.
  * Quiet hours: anything made between 21:00 and 08:00 waits until 08:00.
  * Approve / Reject answers come back to /syncup/callback (signature-checked) or are looked
    up by the cron; the first answer for a payment wins.
"""
import datetime
import hashlib
import hmac
import json
import logging

from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from . import syncup_client
from .models import (BalanceConfirmation, Book, BookLog, BusinessNotifications, Customer,
                     Employee, EmployeePosting, Invoice, Party, Quotation, StaffLogin,
                     SyncUpJobRun, SyncUpMessage, SyncUpSettings)
from .parties import party_for, row_is_visible
from .templatetags.money import format_inr

log = logging.getLogger(__name__)

# ---- the events a business can switch on (console → business page) --------------------
EVENTS = [
    ("customers", "Customers", [
        ("c_bill", "A new bill"),
        ("c_payment", "A payment received, with the new balance"),
        ("c_order", "Their app order approved"),
        ("c_overdue", "A weekly reminder once a bill is 30+ days overdue"),
    ]),
    ("staff", "Employees", [
        ("e_payment", "Their recorded payment approved or rejected"),
        ("e_morning", "A morning list of today's collections"),
    ]),
    ("admins", "Admins", [
        ("a_approval", "A staff payment waiting for approval"),
        ("a_approval_prompt", "…with Approve / Reject buttons in the notification"),
        ("a_order", "A new order from the app"),
        ("a_evening", "An evening summary"),
    ]),
]
EVENT_NAMES = {key for _, _, items in EVENTS for key, _ in items}

QUIET_FROM, QUIET_UNTIL = 21, 8       # local hours — nothing goes out in between
BULK_SIZE = 25                        # per notify/bulk call, to keep SyncUp's request light
MAX_ATTEMPTS = 6
KEEP_DAYS = 14
PROMPT_TTL = 3600                     # SyncUp's cap for a prompt
OVERDUE_DAYS = 30


def _now():
    return timezone.now()


def _cfg():
    return SyncUpSettings.load()


def ready(cfg=None):
    """Master switch on, SyncUp reachable and a public https address to link to."""
    cfg = cfg or _cfg()
    return bool(cfg.messages_enabled and cfg.is_configured and syncup_client.link_base(cfg))


def events_for(business):
    row = BusinessNotifications.objects.filter(user=business).first()
    return set(row.events or []) if row else set()


def set_events(business, events):
    BusinessNotifications.objects.update_or_create(
        user=business, defaults={"events": sorted({e for e in events if e in EVENT_NAMES})})


def enabled(business, event, cfg=None):
    return business is not None and ready(cfg) and event in events_for(business)


# ---- small helpers -----------------------------------------------------------------------
def _brand(user):
    p = getattr(user, "userprofile", None)
    return ((p.business_brand or p.business_title) if p else None) or user.username


def _money(value):
    return "₹" + format_inr(abs(float(value or 0)), 0)


def _url(path):
    return syncup_client.link_base() + path


def _json_total(raw):
    try:
        return round(float(json.loads(raw).get("invoice_total_amt_with_gst", 0) or 0), 2)
    except (ValueError, TypeError, AttributeError):
        return 0.0


def _balance(book, until=None):
    """A ledger's balance (negative = the customer owes), optionally as on a date."""
    logs = BookLog.objects.filter(parent_book=book, is_active=True, change_type__in=[0, 1, 2, 3])
    if until is not None:
        logs = logs.filter(date__date__lte=until)
    return float(logs.aggregate(t=Sum("change"))["t"] or 0)


def _balance_words(balance):
    if balance < -0.5:
        return _money(balance) + " due"
    if balance > 0.5:
        return _money(balance) + " advance"
    return "No dues"


def _after_quiet(now):
    local = timezone.localtime(now)
    if QUIET_UNTIL <= local.hour < QUIET_FROM:
        return now
    day = local.date() if local.hour < QUIET_UNTIL else local.date() + datetime.timedelta(days=1)
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(QUIET_UNTIL)))


def queue(*, business, event, external_id, title, body="", url="", dedupe,
          kind=SyncUpMessage.KIND_NOTIFY, data=None):
    """Add one message to the outbox. Returns it, or None if that event was already queued."""
    try:
        with transaction.atomic():
            return SyncUpMessage.objects.create(
                business=business, event=event, kind=kind, external_id=external_id,
                title=title[:100], body=body[:300], url=url[:500], data=data or {},
                dedupe_key=dedupe[:160], send_after=_after_quiet(_now()))
    except IntegrityError:
        return None


# ---- who gets it ---------------------------------------------------------------------------
def customer_target(customer):
    """The customer's SyncUp id — only with an active login and this row shown in the app."""
    party = party_for(customer)
    if party is not None and party.login_status == Party.LOGIN_ACTIVE and row_is_visible(customer):
        return party.external_id
    return None


def staff_target(employee):
    if employee is None or not employee.is_active:
        return None
    login = StaffLogin.objects.filter(employee=employee, login_status=StaffLogin.LOGIN_ACTIVE).first()
    return login.external_id if login else None


def _staff_postings(business, admins_only=False):
    qs = EmployeePosting.objects.filter(
        business=business, is_active=True, employee__is_active=True,
        employee__staff_login__login_status=StaffLogin.LOGIN_ACTIVE).select_related("employee")
    if admins_only:
        qs = qs.filter(is_admin=True)
    return [(p.employee, "employee-%d" % p.employee_id) for p in qs]


def admin_targets(business):
    return _staff_postings(business, admins_only=True)


def staff_targets(business):
    return _staff_postings(business)


# ---- events (queued after the business's save commits) ----------------------------------
def _later(fn, *args):
    """Run once the save commits; a messaging problem must never break a business action."""
    def run():
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            log.exception("SyncUp message (%s) failed", fn.__name__)
    transaction.on_commit(run)


def bill_created(invoice_id):
    inv = Invoice.objects.select_related("user", "invoice_customer").filter(pk=invoice_id).first()
    if not inv or not inv.invoice_customer_id or not enabled(inv.user, "c_bill"):
        return
    ext = customer_target(inv.invoice_customer)
    if not ext:
        return
    total = _json_total(inv.invoice_json)
    when = inv.invoice_date.strftime("%d %b %Y") if inv.invoice_date else ""
    queue(business=inv.user, event="c_bill", external_id=ext,
          title="%s · Bill #%s" % (_brand(inv.user), inv.invoice_number),
          body=" · ".join(x for x in (_money(total) if total else "", when) if x),
          url=_url("/m/customer/invoice/%d?acct=%d" % (inv.id, inv.invoice_customer_id)),
          dedupe="c_bill:%d" % inv.id)


def payment_in_books(log_id, was_pending):
    """A payment now counts: tell the customer (with the new balance) and, if staff recorded
    it and it was waiting for approval, tell them it's approved."""
    lg = (BookLog.objects.select_related("parent_book__customer", "parent_book__user", "recorded_by")
          .filter(pk=log_id, is_active=True, change_type=0).first())
    if not lg or not lg.parent_book or not lg.parent_book.customer or not lg.parent_book.user:
        return
    business, customer = lg.parent_book.user, lg.parent_book.customer
    brand, amount = _brand(business), _money(lg.change)
    if enabled(business, "c_payment"):
        ext = customer_target(customer)
        if ext:
            queue(business=business, event="c_payment", external_id=ext,
                  title="%s · Payment received %s" % (brand, amount),
                  body="Balance: " + _balance_words(_balance(lg.parent_book)),
                  url=_url("/m/customer/books?acct=%d" % customer.id),
                  dedupe="c_payment:%d" % lg.id)
    if was_pending and lg.recorded_by_id and enabled(business, "e_payment"):
        ext = staff_target(lg.recorded_by)
        if ext:
            queue(business=business, event="e_payment", external_id=ext,
                  title="%s from %s approved" % (amount, customer.customer_name), body=brand,
                  url=_url("/m/employee/customer/%d?biz=%d" % (customer.id, business.id)),
                  dedupe="e_payment:%d" % lg.id)


def payment_pending(log_id):
    """Staff recorded a payment that needs approval: ask the business's admins — with
    Approve / Reject buttons when that's switched on — and try to send straight away."""
    lg = (BookLog.objects.select_related("parent_book__customer", "parent_book__user", "recorded_by")
          .filter(pk=log_id, is_active=False, change_type=0).first())
    if not lg or not lg.parent_book or not lg.parent_book.customer or not lg.parent_book.user:
        return
    business, customer = lg.parent_book.user, lg.parent_book.customer
    if not enabled(business, "a_approval"):
        return
    prompt = "a_approval_prompt" in events_for(business)
    by = lg.recorded_by.name if lg.recorded_by_id else (lg.createdby or "staff")
    ids = []
    for _emp, ext in admin_targets(business):
        m = queue(business=business, event="a_approval", external_id=ext,
                  kind=SyncUpMessage.KIND_APPROVE if prompt else SyncUpMessage.KIND_NOTIFY,
                  title="Approve %s from %s?" % (_money(lg.change), customer.customer_name),
                  body="%s · recorded by %s" % (_brand(business), by),
                  url=_url("/m/employee/approvals?biz=%d" % business.id),
                  data={"log_id": lg.id}, dedupe="a_approval:%d:%s" % (lg.id, ext))
        if m:
            ids.append(m.id)
    if ids:
        flush(only_ids=ids, timeout=syncup_client.QUICK_TIMEOUT)


def payment_rejected(log_id, book_id, employee_id, change):
    book = Book.objects.select_related("customer", "user").filter(pk=book_id).first()
    if not book or not book.customer or not book.user or not enabled(book.user, "e_payment"):
        return
    ext = staff_target(Employee.objects.filter(pk=employee_id).first())
    if ext:
        queue(business=book.user, event="e_payment", external_id=ext,
              title="%s from %s rejected" % (_money(change), book.customer.customer_name),
              body=_brand(book.user),
              url=_url("/m/employee/customer/%d?biz=%d" % (book.customer_id, book.user_id)),
              dedupe="e_payment_rejected:%d" % log_id)


def _order_label(q):
    return "QT-%s" % q.quotation_number          # as the app's order lists show it


def order_placed(quotation_id):
    q = (Quotation.objects.select_related("user", "quotation_customer", "order_employee")
         .filter(pk=quotation_id).first())
    if not q or not q.quotation_customer_id or not enabled(q.user, "a_order"):
        return
    total = _json_total(q.quotation_json)
    by = " by %s" % q.order_employee.name if q.order_employee_id else ""
    for _emp, ext in admin_targets(q.user):
        queue(business=q.user, event="a_order", external_id=ext,
              title="New order from %s%s" % (q.quotation_customer.customer_name,
                                              " · " + _money(total) if total else ""),
              body="%s · order %s%s" % (_brand(q.user), _order_label(q), by),
              url=_url("/m/order/%d?biz=%d" % (q.id, q.user_id)),
              dedupe="a_order:%d:%s" % (q.id, ext))


def order_approved(quotation_id):
    q = Quotation.objects.select_related("user", "quotation_customer").filter(pk=quotation_id).first()
    if not q or not q.quotation_customer_id or not enabled(q.user, "c_order"):
        return
    ext = customer_target(q.quotation_customer)
    if ext:
        queue(business=q.user, event="c_order", external_id=ext,
              title="%s · Order %s approved" % (_brand(q.user), _order_label(q)),
              body="It will be billed soon.",
              url=_url("/m/order/%d?acct=%d" % (q.id, q.quotation_customer_id)),
              dedupe="c_order:%d" % q.id)


# ---- signals: every screen that creates a bill, a payment or an order is covered ---------
@receiver(post_save, sender=Invoice, dispatch_uid="syncup_msg_invoice")
def _invoice_saved(sender, instance, created, raw=False, **kwargs):
    if created and not raw and instance.user_id and instance.invoice_customer_id:
        _later(bill_created, instance.pk)


@receiver(pre_save, sender=BookLog, dispatch_uid="syncup_msg_booklog_before")
def _booklog_before(sender, instance, raw=False, **kwargs):
    instance._syncup_was_active = (
        BookLog.objects.filter(pk=instance.pk).values_list("is_active", flat=True).first()
        if instance.pk and not raw and instance.change_type == 0 else None)


@receiver(post_save, sender=BookLog, dispatch_uid="syncup_msg_booklog")
def _booklog_saved(sender, instance, created, raw=False, **kwargs):
    if raw or instance.change_type != 0:
        return
    was = getattr(instance, "_syncup_was_active", None)
    if instance.is_active and (created or was is False):
        _later(payment_in_books, instance.pk, not created)
    elif created and not instance.is_active:
        _later(payment_pending, instance.pk)


@receiver(pre_save, sender=Quotation, dispatch_uid="syncup_msg_quotation_before")
def _quotation_before(sender, instance, raw=False, **kwargs):
    instance._syncup_old_status = (
        Quotation.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
        if instance.pk and not raw and instance.created_from_cart else None)


@receiver(post_save, sender=Quotation, dispatch_uid="syncup_msg_quotation")
def _quotation_saved(sender, instance, created, raw=False, **kwargs):
    if raw or not instance.created_from_cart:
        return
    old = getattr(instance, "_syncup_old_status", None)
    if old == "DRAFT" and instance.status == "PENDING":
        _later(order_placed, instance.pk)
    elif old == "PENDING" and instance.status == "APPROVED":
        _later(order_approved, instance.pk)


# ---- scheduled messages (run from /cron/syncup) -----------------------------------------
def _once(name, period, fn):
    """Run `fn` once per period (a day or a week), however often the cron calls. A job that
    returns None didn't finish (SyncUp unreachable) and runs again on the next call."""
    run, _ = SyncUpJobRun.objects.get_or_create(name=name)
    if run.period == period:
        return None
    count = fn()
    if count is not None:
        SyncUpJobRun.objects.filter(pk=run.pk).update(period=period, ran_at=_now())
    return count


def _switched_on(event):
    for row in BusinessNotifications.objects.select_related("user", "user__userprofile"):
        if event in (row.events or []) and row.user.is_active:
            yield row.user


def morning_lists(today):
    """Each employee: today's customers to collect at each business that switched it on."""
    model_today = (today.weekday() + 1) % 7            # Customer.DAYS: Sunday=0 … Saturday=6
    sent = 0
    for business in _switched_on("e_morning"):
        balances = dict(Book.objects.filter(user=business).values_list("customer_id", "current_balance"))
        owing = [-float(balances.get(cid) or 0) for cid in
                 Customer.objects.filter(user=business, collection_day=model_today).values_list("id", flat=True)
                 if float(balances.get(cid) or 0) < -0.5]
        if not owing:
            continue
        for _emp, ext in staff_targets(business):
            if queue(business=business, event="e_morning", external_id=ext,
                     title="Today at %s: %d to collect" % (_brand(business), len(owing)),
                     body=_money(sum(owing)) + " due",
                     url=_url("/m/employee/collections?biz=%d" % business.id),
                     dedupe="e_morning:%s:%d:%s" % (ext, business.id, today)):
                sent += 1
    return sent


def evening_summaries(today):
    """Each admin: the day's sales, collections and waiting approvals."""
    sent = 0
    for business in _switched_on("a_evening"):
        sales = sum(_json_total(j) for j in Invoice.objects.filter(user=business, invoice_date=today)
                    .values_list("invoice_json", flat=True))
        collected = abs(float(BookLog.objects.filter(
            parent_book__user=business, is_active=True, change_type=0, date__date=today)
            .aggregate(t=Sum("change"))["t"] or 0))
        waiting = BookLog.objects.filter(parent_book__user=business, is_active=False,
                                         change_type=0).count()
        if not (sales or collected or waiting):
            continue
        body = "Sales %s · collected %s%s" % (_money(sales), _money(collected),
                                               " · %d to approve" % waiting if waiting else "")
        for _emp, ext in admin_targets(business):
            if queue(business=business, event="a_evening", external_id=ext,
                     title="%s today" % _brand(business), body=body,
                     url=_url("/m/employee/?biz=%d" % business.id),
                     dedupe="a_evening:%s:%d:%s" % (ext, business.id, today)):
                sent += 1
    return sent


def weekly_overdue(today):
    """Each customer shown in the app whose oldest unpaid bill is 30+ days old."""
    from .views.m.employee import _overdue_days          # the staff app's own FIFO rule
    week = "%d-W%02d" % today.isocalendar()[:2]
    sent = 0
    for business in _switched_on("c_overdue"):
        ages = _overdue_days(business, today)
        balances = dict(Book.objects.filter(user=business).values_list("customer_id", "current_balance"))
        late = [cid for cid, days in ages.items() if days >= OVERDUE_DAYS
                and float(balances.get(cid) or 0) < -0.5]
        for c in Customer.objects.filter(pk__in=late):
            ext = customer_target(c)
            if ext and queue(business=business, event="c_overdue", external_id=ext,
                             title="%s due at %s" % (_money(balances.get(c.id)), _brand(business)),
                             body="Your oldest unpaid bill is %d days old." % ages[c.id],
                             url=_url("/m/customer/books?acct=%d" % c.id),
                             dedupe="c_overdue:%d:%s" % (c.id, week)):
                sent += 1
    return sent


def _tile_text(party, rows):
    balances = Book.objects.filter(customer_id__in=[r.id for r in rows]).values_list(
        "current_balance", flat=True)
    due = sum(-float(b or 0) for b in balances if float(b or 0) < -0.5)
    shops = len({r.user_id for r in rows})
    return (_money(due) + " due" if due else "No dues") + (" · %d shops" % shops if shops > 1 else "")


def refresh_tiles(clear=False):
    """Put "₹… due · N shops" on each customer's GSTSync tile — only where it changed. With
    `clear`, remove the subtitles instead (the setting was switched off). Returns how many
    changed, or None if SyncUp stopped answering (the rest wait for the next run)."""
    from .parties import app_link, visible_rows
    updated = 0
    parties = Party.objects.exclude(tile_text="") if clear else Party.objects.filter(
        login_status=Party.LOGIN_ACTIVE)
    for party in parties:
        rows = [] if clear else visible_rows(party)
        if not clear and not rows:
            continue
        text = "" if clear else _tile_text(party, rows)
        if text == party.tile_text:
            continue
        if party.login_status == Party.LOGIN_ACTIVE:
            try:
                syncup_client.update_app_link(party.external_id, url=app_link(party),
                                              description=text, timeout=syncup_client.QUICK_TIMEOUT)
            except syncup_client.SyncUpError as e:
                log.warning("Tile refresh for %s failed: %s", party.external_id, e)
                if e.status is None:
                    return None
                continue
        Party.objects.filter(pk=party.pk).update(tile_text=text)
        updated += 1
    return updated


def run_schedules(now=None):
    """Called by /cron/syncup; each job runs once in its window."""
    cfg = _cfg()
    if not cfg.is_configured:
        return {}
    out = {}
    if not (ready(cfg) and cfg.tile_due) and Party.objects.exclude(tile_text="").exists():
        out["tiles_cleared"] = refresh_tiles(clear=True)          # switched off since
    if not ready(cfg):
        return {k: v for k, v in out.items() if v is not None}
    local = timezone.localtime(now or _now())
    today = local.date()
    if local.weekday() != 6 and 9 <= local.hour < 12:              # not Sundays
        out["morning"] = _once("morning", today.isoformat(), lambda: morning_lists(today))
    if 19 <= local.hour < QUIET_FROM:
        out["evening"] = _once("evening", today.isoformat(), lambda: evening_summaries(today))
    if local.weekday() == 0 and 10 <= local.hour < QUIET_FROM:     # Mondays
        week = "%d-W%02d" % today.isocalendar()[:2]
        out["overdue"] = _once("overdue", week, lambda: weekly_overdue(today))
    if cfg.tile_due and local.hour >= 7:
        out["tiles"] = _once("tiles", today.isoformat(), refresh_tiles)
    return {k: v for k, v in out.items() if v is not None}


# ---- sending --------------------------------------------------------------------------------
def _retry_later(msgs, error):
    for m in msgs:
        m.attempts += 1
        m.last_error = str(error)[:300]
        m.failed = m.attempts >= MAX_ATTEMPTS
        m.sent_at = None
        m.save(update_fields=["attempts", "last_error", "failed", "sent_at"])


def _give_up(m, error):
    """Not worth retrying — e.g. the person's SyncUp login is gone."""
    m.failed, m.sent_at, m.last_error = True, None, str(error or "Not delivered")[:300]
    m.save(update_fields=["failed", "sent_at", "last_error"])


def flush(limit=200, only_ids=None, timeout=None):
    """Send what's due. Pushes go ≤25 per notify/bulk call; prompts one by one. A failed call is
    retried on a later run (up to MAX_ATTEMPTS); a person who's gone is not retried.

    Each message is claimed (sent_at set) before it's sent, so the cron and the immediate
    try for an approval can't both send it."""
    cfg = _cfg()
    if not cfg.is_configured:
        return {"sent": 0, "failed": 0}
    now = _now()
    qs = SyncUpMessage.objects.filter(sent_at__isnull=True, failed=False, send_after__lte=now)
    if only_ids is not None:
        qs = qs.filter(id__in=list(only_ids))
    ids = list(qs.order_by("id").values_list("id", flat=True)[:limit])
    claimed = [i for i in ids if SyncUpMessage.objects.filter(
        pk=i, sent_at__isnull=True, failed=False).update(sent_at=now)]
    msgs = list(SyncUpMessage.objects.filter(id__in=claimed).order_by("id"))
    sent = failed = 0

    pushes = [m for m in msgs if m.kind == SyncUpMessage.KIND_NOTIFY]
    for i in range(0, len(pushes), BULK_SIZE):
        chunk = pushes[i:i + BULK_SIZE]
        try:
            results = syncup_client.notify_bulk(
                [{"external_id": m.external_id, "title": m.title, "body": m.body, "url": m.url}
                 for m in chunk], timeout=timeout)
        except syncup_client.SyncUpError as e:
            _retry_later(chunk, e)
            continue
        for m, res in zip(chunk, list(results) + [None] * (len(chunk) - len(results))):
            if isinstance(res, dict) and "error" not in res:
                m.delivered = int(res.get("delivered") or 0)
                m.save(update_fields=["delivered"])
                sent += 1
            else:
                _give_up(m, res.get("error") if isinstance(res, dict) else "No result from SyncUp")
                failed += 1

    prompts = [m for m in msgs if m.kind == SyncUpMessage.KIND_APPROVE]
    for n, m in enumerate(prompts):
        if not BookLog.objects.filter(pk=m.data.get("log_id"), is_active=False).exists():
            m.answered_at, m.answer = now, "moot"   # already approved or rejected elsewhere
            m.save(update_fields=["answered_at", "answer"])
            continue
        try:
            reply = syncup_client.create_action(m.external_id, {
                "type": "approve", "title": m.title, "message": m.body,
                "approve_label": "Approve", "reject_label": "Reject",
                "callback_url": _url("/syncup/callback"), "ttl_seconds": PROMPT_TTL,
            }, timeout=timeout)
        except syncup_client.SyncUpError as e:
            if e.status == 404:
                _give_up(m, e)
                failed += 1
                continue
            _retry_later([m], e)
            if e.status is None:                     # unreachable — the rest wait, untried
                SyncUpMessage.objects.filter(id__in=[p.id for p in prompts[n + 1:]]).update(sent_at=None)
                break
            continue
        m.request_id = str(reply.get("request_id") or "")
        m.delivered = int(reply.get("delivered") or 0)
        m.save(update_fields=["request_id", "delivered"])
        sent += 1

    SyncUpMessage.objects.filter(created_at__lt=now - datetime.timedelta(days=KEEP_DAYS)).delete()
    return {"sent": sent, "failed": failed}


# ---- Approve / Reject answers ---------------------------------------------------------------
def verify_signature(body, header, secret):
    """Does X-SyncUp-Signature match an HMAC-SHA256 of the raw body with our signing secret?"""
    if not secret:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header or "")


def delete_booklog(lg):
    """Delete a ledger entry; a staff payment still waiting for approval counts as rejected,
    and the employee who recorded it is told. (Explicit rather than a delete signal, which
    would slow every bulk delete of ledger entries.)"""
    if lg.change_type == 0 and not lg.is_active and lg.recorded_by_id and lg.parent_book_id:
        _later(payment_rejected, lg.pk, lg.parent_book_id, lg.recorded_by_id,
               float(lg.change or 0))
    lg.delete()


def approve_pending_payment(lg):
    """Approve a staff payment — shared by the staff app's Approvals and the notification."""
    from .utils import recalculate_book_current_balance
    lg.is_active = True
    lg.save()
    book = lg.parent_book
    recalculate_book_current_balance(book)
    book.last_log = lg
    book.save()


def apply_answer(request_id, value):
    """Act on an admin's Approve / Reject. Safe to call twice; the first answer wins, and only
    someone still an admin at that business can decide."""
    m = (SyncUpMessage.objects.select_related("business")
         .filter(request_id=str(request_id), kind=SyncUpMessage.KIND_APPROVE).first())
    if not m or not request_id:
        return "ignored"
    # Claim the answer in one UPDATE, so a callback and the cron's look-up can't both act.
    if not SyncUpMessage.objects.filter(pk=m.pk, answered_at__isnull=True).update(
            answered_at=_now(), answer=str(value)[:20]):
        return "ignored"
    emp_id = m.external_id.split("-", 1)[1] if m.external_id.startswith("employee-") else ""
    still_admin = emp_id.isdigit() and EmployeePosting.objects.filter(
        employee_id=int(emp_id), business=m.business, is_admin=True, is_active=True,
        employee__is_active=True,
        employee__staff_login__login_status=StaffLogin.LOGIN_ACTIVE).exists()
    if not still_admin:
        return "not an admin any more"
    if value not in ("approved", "rejected"):
        return "ignored"
    with transaction.atomic():
        # Locked, so two admins answering at once can't both act on the same payment.
        lg = (BookLog.objects.select_for_update().select_related("parent_book")
              .filter(pk=m.data.get("log_id"), is_active=False, change_type=0,
                      parent_book__user=m.business).first())
        if lg is None:
            return "already handled"
        if value == "approved":
            approve_pending_payment(lg)
        else:
            delete_booklog(lg)
    return value


def reconcile(timeout=None):
    """Look up answers whose callback never arrived (prompts sent within the last ~75 min)."""
    cutoff = _now() - datetime.timedelta(seconds=PROMPT_TTL + 900)
    done = 0
    for m in (SyncUpMessage.objects.filter(kind=SyncUpMessage.KIND_APPROVE, answered_at__isnull=True,
                                           sent_at__gte=cutoff).exclude(request_id="")[:50]):
        if not BookLog.objects.filter(pk=m.data.get("log_id"), is_active=False).exists():
            SyncUpMessage.objects.filter(pk=m.pk).update(answered_at=_now(), answer="moot")
            continue
        try:
            state = syncup_client.action_status(m.request_id, timeout=timeout)
        except syncup_client.SyncUpError:
            continue
        if state.get("status") == "completed":
            apply_answer(m.request_id, str(state.get("value") or ""))
            done += 1
        elif state.get("status") == "expired":
            SyncUpMessage.objects.filter(pk=m.pk).update(answered_at=_now(), answer="expired")
    return done


# ---- balance confirmation ------------------------------------------------------------------
def request_balance_confirmations(business, as_of, admin=None):
    """Ask every customer this business shows in the app to confirm their balance on `as_of`.
    Returns how many were asked."""
    if not ready():
        raise ValueError("Turn on SyncUp messages under Console → Settings first.")
    brand, asked = _brand(business), 0
    for c in Customer.objects.filter(user=business, is_mobile_user=True).order_by("id"):
        ext = customer_target(c)
        if not ext:
            continue
        book = Book.objects.filter(customer=c).first()
        balance = _balance(book, until=as_of) if book else 0.0
        bc = BalanceConfirmation.objects.create(customer=c, balance=balance, as_of=as_of,
                                                requested_by=admin)
        queue(business=business, event="c_confirm", external_id=ext,
              title="Please confirm your balance with %s" % brand,
              body="%s on %s" % (_balance_words(balance), as_of.strftime("%d %b %Y")),
              url=_url("/m/customer/confirm/%d?acct=%d" % (bc.id, c.id)),
              dedupe="c_confirm:%d" % bc.id)
        asked += 1
    return asked


def confirmation_summary(business, limit=3):
    return list(BalanceConfirmation.objects.filter(customer__user=business)
                .values("as_of").annotate(asked=Count("id"),
                                          confirmed=Count("id", filter=Q(confirmed_at__isnull=False)))
                .order_by("-as_of")[:limit])


def stats():
    since = _now() - datetime.timedelta(hours=24)
    qs = SyncUpMessage.objects
    return {"waiting": qs.filter(sent_at__isnull=True, failed=False).count(),
            "sent_24h": qs.filter(sent_at__gte=since).count(),
            "failed_24h": qs.filter(failed=True, created_at__gte=since).count()}
