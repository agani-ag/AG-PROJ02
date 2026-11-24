"""Console: the notice every business owner sees when they sign in.

One message, one switch. It is the console's own voice — a renewal that is due, a price
change, a day of downtime — so it says who it is from and what it is for. Changing the text
raises its version, which brings it back for anyone who had already closed the old one.
"""
import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from ..console_auth import console_required
from ..models import ConsoleNotice

# What the form opens with the first time, so a notice can be sent in one edit. It names
# GSTSync, because a bill that doesn't say who it is from is the kind people ignore — or
# complain about afterwards.
DEFAULT = {
    "title": "Your GSTSync subscription is due for renewal",
    "body": ("Your subscription covers the server, the daily backups, the mobile app and "
             "support. It ends on the date below.\n\n"
             "Renew before then and nothing changes. After that date billing, collections "
             "and the mobile app stop working until the renewal is received."),
    "contact": "To renew, contact us on 98765 43210 or reply to our WhatsApp.",
    "action_text": "",
}

FIELDS = ("title", "body", "contact", "action_text", "action_url")


@console_required
def notice(request):
    """Edit the notice, switch it on or off, and see it exactly as an owner will."""
    row = ConsoleNotice.load()
    if request.method == "POST":
        return _save(request, row)
    form = {f: getattr(row, f) for f in FIELDS}
    if not row.pk:                                  # never set up: start from the draft
        form.update(DEFAULT)
    form["amount"] = row.amount if row.amount is not None else ""
    form["due_date"] = row.due_date.isoformat() if row.due_date else ""
    return render(request, "console/notice.html",
                  {"row": row, "form": form, "errors": []})


def _save(request, row):
    d = request.POST
    errors = []
    form = {f: (d.get(f) or "").strip() for f in FIELDS}
    form["amount"] = (d.get("amount") or "").strip()
    form["due_date"] = (d.get("due_date") or "").strip()
    enabled = bool(d.get("enabled"))

    if not form["title"]:
        errors.append("A notice needs a title — it is the line people actually read.")
    if not form["body"]:
        errors.append("A notice needs some words under the title.")
    if form["action_text"] and not form["action_url"]:
        errors.append("A button needs a link, or leave the button text empty.")

    amount = None
    if form["amount"]:
        try:
            amount = Decimal(form["amount"].replace(",", ""))
        except (InvalidOperation, ValueError):
            errors.append("That amount is not a number.")
        else:
            if amount < 0:
                errors.append("That amount cannot be negative.")

    due = None
    if form["due_date"]:
        try:
            due = datetime.date.fromisoformat(form["due_date"])
        except ValueError:
            errors.append("That date is not a date I can read. Use the date picker.")

    if errors:
        return render(request, "console/notice.html",
                      {"row": row, "form": form, "enabled": enabled, "errors": errors},
                      status=400)

    # Anything the owner would see counts as a new notice, so it reaches the people who
    # closed the last one.
    changed = (any(getattr(row, f) != form[f] for f in FIELDS)
               or row.amount != amount or row.due_date != due)
    for f in FIELDS:
        setattr(row, f, form[f])
    row.amount, row.due_date, row.enabled = amount, due, enabled
    if changed:
        row.version += 1
    row.updated_by = str(request.platform_admin)
    row.save()
    messages.success(request, "Notice saved and switched on." if enabled
                     else "Notice saved. It is switched off, so nobody sees it.")
    return redirect("console_notice")


@console_required
@require_POST
def notice_toggle(request):
    """The switch on its own, for turning a notice off the moment it stops being true."""
    row = ConsoleNotice.load()
    if not (row.title or row.body):
        messages.error(request, "Write the notice first.")
        return redirect("console_notice")
    row.enabled = not row.enabled
    row.updated_by = str(request.platform_admin)
    row.save()
    messages.success(request, "Notice is now showing to every business."
                     if row.enabled else "Notice switched off.")
    return redirect("console_notice")
