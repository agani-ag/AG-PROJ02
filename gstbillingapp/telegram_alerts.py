"""Telegram login alerts — every sign-in, announced to the business's own Telegram group.

Two gates, the same shape as the reports: a platform admin allows login alerts for a business
on the console, and the business itself then says — on its own profile page — which logins it
wants (desktop, mobile) and which of its groups hear them.

  * **Owner** — signing in to the desktop app, however they did it (password, passkey,
    Switch User). Hooked to Django's own `user_logged_in`, so no sign-in route can be missed.
  * **Employee** — opening the staff app. An admin is an employee with Admin on their posting,
    so their logins are covered by the same alert.
  * **Customer** — opening their ledger in the SyncUp app. Every business that shows them
    hears about it; each only ever hears about its own people.

The **console** is deliberately never announced: a platform admin is not a Django user and
never passes through here.

Opening the app is what counts on mobile: the tile's link (?t=) means a fresh login and is
announced — 9 am and again at 11 am are two alerts. Pages reached from inside the app carry no
link and stay silent, so a day's browsing doesn't become thirty messages; if they simply leave
the tab open, coming back to it counts again only after SESSION_GAP. A desktop sign-in is a
single event, so every one of them is announced.

An alert goes out ON THE SPOT: it is queued like everything else and then given one quick try
(INSTANT_TIMEOUT), so a 10:00 login reaches the group at 10:00. Whatever that try can't deliver
stays in the queue for /cron/syncup, and the message carries the real login time either way.
The shape follows SyncUp's own "Device Login" notice.
"""
import logging
import time
import uuid

from django.contrib.auth.signals import user_logged_in
from django.db.models import F
from django.dispatch import receiver
from django.utils import timezone

from .models import BusinessTelegram, StaffLogin, SyncUpMessage
from .telegram_reports import SEPARATOR, available, brand, chats
from .utils import _escape_md

log = logging.getLogger(__name__)

# Opening the tile in the SyncUp app carries the ?t= link, so that IS a fresh login and is
# announced however soon it comes — TAP_GAP only swallows a double tap and the token-dropping
# redirect that follows it. Arriving without the link (the same tab, the back button, a
# bookmark) is the same visit continuing, and only counts again after SESSION_GAP.
TAP_GAP = 120
SESSION_GAP = 6 * 3600
# A login alert is sent on the spot, not left for the cron — but the person signing in waits
# no longer than this for it. Whatever doesn't get through is picked up by /cron/syncup.
INSTANT_TIMEOUT = 3
SESSION_KEY = "m_open_at"          # holds when this browser's current visit started
THIN_SEP = "-" * 12

OWNER, EMPLOYEE, CUSTOMER = "owner", "employee", "customer"
ROLE_WORDS = {OWNER: "Owner", EMPLOYEE: "Employee", CUSTOMER: "Customer"}

# Enough of the user agent to recognise the device, without pretending to be analytics.
_PLATFORMS = [("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"),
              ("Windows", "Windows"), ("Macintosh", "Mac"), ("Linux", "Linux")]
_BROWSERS = [("Edg/", "Edge"), ("OPR/", "Opera"), ("SamsungBrowser", "Samsung Internet"),
             ("Chrome", "Chrome"), ("Firefox", "Firefox"), ("Safari", "Safari")]


def device_name(user_agent):
    """"Android · Chrome" — "" when the agent says nothing useful."""
    agent = user_agent or ""
    platform = next((name for needle, name in _PLATFORMS if needle in agent), "")
    browser = next((name for needle, name in _BROWSERS if needle in agent), "")
    return " · ".join(p for p in (platform, browser) if p)


def _agent(request):
    return device_name(request.META.get("HTTP_USER_AGENT") if request else "")


def _bump(row):
    """Count this login on the Party / StaffLogin. Returns the new count, or None."""
    if row is None:
        return None
    type(row).objects.filter(pk=row.pk).update(app_opens=F("app_opens") + 1,
                                               last_open_at=timezone.now())
    return (row.app_opens or 0) + 1


def message(who, role, count, when, device, detail="", at=""):
    """The MarkdownV2 body — one screenful, the same shape as SyncUp's device notice.

    `at` is the business this login belongs to. It is worth a line because one Telegram group
    can serve several businesses (a shared chat id), and "KMR opened the app" is no use if you
    can't tell which of your shops they opened. The owner's own sign-in already says it in the
    name, so it isn't repeated there."""
    lines = ["*🤝 App Login 🔔*", "", _escape_md(THIN_SEP), "*%s*" % _escape_md(who.upper())]
    if detail:
        lines.append("_%s_" % _escape_md(detail))
    if at and at.upper() != who.upper():
        lines.append("*🏢 %s*" % _escape_md(at))
    lines.append(_escape_md(SEPARATOR))
    lines.append("*%s%s*" % (_escape_md(ROLE_WORDS.get(role, "User")),
                             " \\| 📲 %d Times" % count if count else ""))
    lines.append("*🕒 %s*" % _escape_md(when.strftime("%I:%M %p · %d %b %Y").lstrip("0")))
    if device:
        lines.append("*📱 %s*" % _escape_md(device))
    lines.append(_escape_md(THIN_SEP))
    lines.append("")
    lines.append("🔄  _SyncUp \\| %s_" % _escape_md(when.strftime("%d %b %Y")))
    return "\n".join(lines)


def settings_for(business):
    """This business's login-alert setup, or None when it has none yet."""
    return BusinessTelegram.objects.filter(user=business).first()


def wanted(business, role, row=None):
    """The groups this login should go to — empty when nobody asked for it.

    Two gates, as with the reports: we allow it on the console (`login_alerts`), and the
    business chooses on its own profile page which logins it wants and which of its groups
    hear them. No group picked means every active one."""
    row = row if row is not None else settings_for(business)
    if row is None or not row.login_alerts or not available(business):
        return []
    if not (row.notify_desktop if role == OWNER else row.notify_mobile):
        return []
    picked = [c for c in row.alert_chats.all() if c.is_active]
    return picked or chats(business)


def announce(businesses, *, who, role, when, device, count=None, detail=""):
    """Queue the alert for every business that asked to hear this login. Returns how many."""
    from .syncup_messages import queue
    targets = [(b, wanted(b, role)) for b in businesses]
    targets = [(b, group) for b, group in targets if group]
    if not targets:
        return 0
    # A login is a one-off, so its key is unique: two sign-ins in the same second both go.
    # What stops a flood is SESSION_GAP (mobile) — never this key.
    stamp = uuid.uuid4().hex[:10]
    ids = []
    for business, group in targets:
        # Written per business, because each one's copy names itself (a group may be shared).
        text = message(who, role, count, when, device, detail, at=brand(business))
        for chat in group:
            # any_time: a login at 10 pm is news at 10 pm, not at 8 the next morning.
            m = queue(business=business, event="login", external_id=chat.chat_id,
                      kind=SyncUpMessage.KIND_TELEGRAM, title="App login", text=text,
                      dedupe="tg_login:%s:%d:%s:%s" % (role, business.id, chat.chat_id, stamp),
                      any_time=True)
            if m:
                ids.append(m.id)
    _try_now(ids)
    return len(ids)


def _try_now(ids):
    """One quick try, so a 10:00 login reaches the group at 10:00 rather than on the next cron
    run. Capped at INSTANT_TIMEOUT: nobody signing in waits longer than that, and anything
    that doesn't get through stays queued for /cron/syncup to send.

    (A message that times out here may in fact have been delivered, and would then go a second
    time from the cron. A rare duplicate is the right trade for not losing the alert.)"""
    if not ids:
        return
    from .syncup_messages import flush
    try:
        flush(only_ids=ids, timeout=INSTANT_TIMEOUT)
    except Exception:  # noqa: BLE001 — never stand between anyone and their sign-in
        log.exception("Instant login alert failed; it stays queued for the cron")


def note_app_open(request, actor):
    """Called on every /m/ page — cheap, and only does anything when a visit begins.

    Returns how many alerts were queued (0 most of the time)."""
    now = time.time()
    # Tapping the tile in the app brings the ?t= link with it — that is someone opening the
    # app, so it counts even if they were here an hour ago. Pages they reach from inside the
    # app carry no link, and only count once the visit has gone cold.
    from_app = bool(request.GET.get("t"))
    if now - (request.session.get(SESSION_KEY) or 0) < (TAP_GAP if from_app else SESSION_GAP):
        return 0                                   # same visit: no writes at all
    request.session[SESSION_KEY] = now

    when = timezone.localtime()
    if actor["role"] == "employee":
        person = actor["employee"]
        who, detail, role = person.name, "", EMPLOYEE
        count = _bump(StaffLogin.objects.filter(employee=person).first())
    else:
        party = actor.get("party")
        row = actor.get("customer") or actor.get("primary")
        who = (party.name if party is not None else (row.customer_name if row else "Customer"))
        detail, role = ((row.customer_place or "") if row else ""), CUSTOMER
        count = _bump(party)
    # The count is kept whether or not anyone is listening, so the console always has it.
    return announce(actor["businesses"], who=who, role=role, when=when, count=count,
                    device=_agent(request), detail=detail)


@receiver(user_logged_in, dispatch_uid="telegram_alert_desktop_login")
def _desktop_login(sender, request, user, **kwargs):
    """Every desktop sign-in — password, passkey or Switch User — lands here, because Django
    fires this for all of them. A console sign-in never does: a platform admin is not a
    Django user at all."""
    try:
        profile = getattr(user, "userprofile", None)
        who = ((profile.business_brand or profile.business_title) if profile else "") or \
            user.username
        announce([user], who=who, role=OWNER, when=timezone.localtime(),
                 device=_agent(request), detail="@%s" % user.username)
    except Exception:  # noqa: BLE001 — an alert must never stand between anyone and sign-in
        log.exception("Desktop login alert failed")
