"""Console: SyncUp settings — how GSTSync reaches SyncUp's Partner API.

Kept in the database (models.SyncUpSettings, one row) rather than settings.py, so a
platform admin can set SyncUp up, rotate the partner key or move hosts without server
access or a restart.
"""
import re
from urllib.parse import urlsplit

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from ..console_auth import console_required
from ..models import Party, StaffLogin, SyncUpSettings
from ..syncup_client import check_connection

_DOMAIN = re.compile(r"^(?=.{1,100}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")
# Plain http is only accepted for a SyncUp on this machine (development). Anywhere else
# the partner key would cross the network in the clear.
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _clean_base(value, *, https_only, label):
    """(address, error) — a bare scheme://host[:port][/path] with no trailing slash."""
    value = (value or "").strip().rstrip("/")
    if not value:
        return "", None
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return value, "%s must be a full address, like https://example.com." % label
    if parts.scheme == "http" and (https_only or parts.hostname not in _LOCAL_HOSTS):
        return value, "%s must start with https://." % label
    if parts.query or parts.fragment:
        return value, "%s can't contain ? or #." % label
    return value, None


def domain_locked():
    """The login domain is part of every issued login's email in SyncUp, so it can't change
    once one exists — those customers and employees would be locked out."""
    return (Party.objects.exclude(login_status=Party.LOGIN_NONE).exists()
            or StaffLogin.objects.exclude(login_status=StaffLogin.LOGIN_NONE).exists())


@console_required
def syncup_settings(request):
    cfg = SyncUpSettings.load()
    locked = domain_locked()
    form = {"api_base": cfg.api_base, "link_base": cfg.link_base,
            "timeout": cfg.timeout, "login_domain": cfg.login_domain}

    if request.method == "POST":
        d = request.POST
        errors = []
        api_base, err = _clean_base(d.get("api_base"), https_only=False, label="SyncUp address")
        if err:
            errors.append(err)
        if api_base.lower().endswith("/partner/v1"):          # accept the full API URL too
            api_base = api_base[:-len("/partner/v1")]
        link_base, err = _clean_base(d.get("link_base"), https_only=True,
                                     label="This site's address")
        if err:
            errors.append(err)
        try:
            timeout = int(d.get("timeout") or 0)
        except ValueError:
            timeout = 0
        if not 1 <= timeout <= 30:
            errors.append("Timeout must be between 1 and 30 seconds.")
        domain = (d.get("login_domain") or "").strip().lower()
        if locked and domain != cfg.login_domain:
            errors.append("The login domain can't change now — issued logins already use it "
                          "in SyncUp.")
        elif not _DOMAIN.match(domain):
            errors.append("Login domain must look like gstsync.app.")
        key = (d.get("partner_key") or "").strip()
        if key and len(key) > 200:
            errors.append("That partner key is too long.")

        if errors:
            form.update(api_base=d.get("api_base") or "", link_base=d.get("link_base") or "",
                        timeout=d.get("timeout") or "", login_domain=d.get("login_domain") or "")
            return render(request, "console/syncup_settings.html",
                          {"cfg": cfg, "form": form, "locked": locked, "errors": errors},
                          status=400)

        cfg.api_base, cfg.link_base = api_base, link_base
        cfg.timeout, cfg.login_domain = timeout, domain
        if d.get("clear_key"):
            cfg.partner_key = ""
        elif key:                                       # blank keeps the current key
            cfg.partner_key = key
        cfg.updated_by = request.platform_admin
        cfg.save()
        messages.success(request, "SyncUp settings saved.")
        return redirect("console_syncup")

    return render(request, "console/syncup_settings.html",
                  {"cfg": cfg, "form": form, "locked": locked, "errors": []})


@console_required
@require_POST
def syncup_test(request):
    ok, message = check_connection()
    (messages.success if ok else messages.error)(request, message)
    return redirect("console_syncup")
