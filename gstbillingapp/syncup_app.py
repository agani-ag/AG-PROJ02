"""The SyncUp app's Google Play listing — one URL, set under Console → Settings, used by every
page that offers the app.

Every link to the listing carries Play's install referrer (utm_source=gstsync,
utm_medium=<where>), so the Play Console shows which place brought each install. With no URL
set, `listing()` returns None and every "get the app" block and share button stays hidden —
nothing is ever half-shown.
"""
from functools import lru_cache
from urllib.parse import parse_qs, quote, urlsplit
import re

from django.contrib.staticfiles import finders
from django.templatetags.static import static

from .models import SyncUpSettings

PLAY_DETAILS = "https://play.google.com/store/apps/details?id="
_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")

# Google's official "Get it on Google Play" badge, if it's been added to static/. Without
# it pages show their own text button — the badge artwork is Google's and isn't recreated.
BADGE = "gstbillingapp/images/google-play-badge.png"

DEFAULT_CUSTOMER_TEXT = ("Hello {customer}, see your {business} ledger, bills and orders in the "
                         "SyncUp app: {link}\nYour login is sent to you separately.")
DEFAULT_SHARE_TEXT = "Get the SyncUp app for {business}: {link}"


def parse_play_url(value):
    """(listing URL, package id) for a Google Play app, or ("", "") if it isn't one.

    Accepts the full https link (extra parameters such as &hl= are dropped), a market://
    link, or the bare package id, and always returns the canonical https form."""
    value = (value or "").strip()
    if not value:
        return "", ""
    if _PACKAGE.match(value):
        package = value
    else:
        parts = urlsplit(value)
        on_play = (parts.scheme in ("https", "http") and parts.hostname == "play.google.com"
                   and parts.path.rstrip("/") == "/store/apps/details")
        if not (on_play or parts.scheme == "market"):
            return "", ""
        package = (parse_qs(parts.query).get("id") or [""])[0].strip()
    if not _PACKAGE.match(package):
        return "", ""
    return PLAY_DETAILS + package, package


def play_link(url, medium):
    """The listing URL tagged with Play's install referrer for one place (`medium`)."""
    return url + "&referrer=" + quote("utm_source=gstsync&utm_medium=%s" % medium, safe="")


@lru_cache(maxsize=1)
def badge_url():
    """Static URL of the official badge if it's been added, else ""."""
    return static(BADGE) if finders.find(BADGE) else ""


def _fill(template, **values):
    # str.replace, not str.format: an admin's text with a stray { or } must never break a page.
    for key, value in values.items():
        template = template.replace("{%s}" % key, value or "")
    return template


def customer_text(cfg, *, customer, business, link):
    """The message an employee sends a customer — never carries a login or password."""
    return _fill((cfg.customer_share_text or "").strip() or DEFAULT_CUSTOMER_TEXT,
                 customer=customer, business=business, link=link)


def share_text(cfg, *, business, link):
    """The general "get the app" message a business sends from its dashboard or profile."""
    return _fill((cfg.share_text or "").strip() or DEFAULT_SHARE_TEXT,
                 business=business, link=link)


def customer_invite(customer, business):
    """The text an employee sends to invite a customer, or "" when no Play URL is set. The
    caller decides WHO may be invited (only customers the business shows in the app)."""
    cfg = SyncUpSettings.load()
    app = listing(cfg)
    if not app:
        return ""
    return customer_text(cfg, customer=customer, business=business, link=app["staff"])


def listing(cfg=None):
    """Everything a page needs about the app, or None when no Play URL is set."""
    cfg = cfg or SyncUpSettings.load()
    url, package = parse_play_url(cfg.play_url)
    if not url:
        return None
    return {
        "url": url,
        "package": package,
        "on_landing": cfg.play_on_landing,
        "badge": badge_url(),
        # One tagged link per place, so installs can be told apart in the Play Console.
        "landing": play_link(url, "landing"),
        "business": play_link(url, "business"),
        "staff": play_link(url, "staff"),
        "console": play_link(url, "console"),
    }
