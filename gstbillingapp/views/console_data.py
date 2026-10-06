"""Console: Data — the tables, their rows, and one row at a time.

The last resort. Every other console screen shows one thing well; this one shows everything,
and lets a platform admin repair what no screen can reach. The rules it plays by live in
dbviewer.py — secrets hidden, computed fields flagged, saves through the model so validation
and signals run. Nothing here touches the schema.

Each write logs who did it, to which table and row, and which fields moved. A log line, not an
audit table: enough to answer "what happened at 3pm", without a new place for data to rot.
"""
import logging

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .. import dbviewer
from ..console_auth import console_required

log = logging.getLogger(__name__)


def _model_or_404(label):
    model = dbviewer.find(label)
    if model is None:
        raise Http404("No such table")
    return model


def _back(label, params):
    """Back to the grid the admin came from, with their table, filters and page intact."""
    carried = params.copy() if params else None
    if carried is not None:
        carried.pop("t", None)                   # the table is named once, below
    query = carried.urlencode() if carried else ""
    return "/console/data?t=%s%s" % (label, "&" + query if query else "")


@console_required
def browse(request):
    """The whole screen: pick a table, see its rows, filter any column, open one.

    One page and one address — the table is `?t=`, the filters are `?f_<column>=`, so a view
    you've narrowed down is a link you can keep or send to yourself."""
    label = (request.GET.get("t") or dbviewer.default_label()).lower()
    model = _model_or_404(label)
    q = (request.GET.get("q") or "").strip()
    columns = dbviewer.columns(model)

    found = model._default_manager.all()
    related = [f.name for f in columns if f.is_relation]
    if related:
        found = found.select_related(*related)
    found, typed, filtered = dbviewer.apply_filters(model, found, request.GET)
    found = found.order_by("-pk")

    page = Paginator(found, dbviewer.PAGE_SIZE).get_page(request.GET.get("page"))
    carried = request.GET.copy()                 # keep the view when turning the page
    carried.pop("page", None)
    carried["t"] = label
    return render(request, "console/data_browse.html", {
        "label": label, "model_name": model._meta.object_name,
        "verbose": model._meta.verbose_name_plural, "q": q,
        "tables": [{"label": lab, "name": name, "count": count}
                   for lab, name, count in dbviewer.choices()],
        "columns": [{"name": f.name, "title": f.verbose_name,
                     "filter": typed.get(f.name, "")} for f in columns],
        "page": page,
        "rows": [{"pk": row.pk, "cells": [dbviewer.cell(row, f) for f in columns]}
                 for row in page],
        "filtered": filtered,
        "carried": carried.urlencode(),
    })


def _row_page(request, model, label, instance, form):
    """The shared edit/add screen."""
    is_new = instance is None or instance.pk is None
    shown = []
    for field in dbviewer.fields_of(model):
        if field.name in form.fields or field.primary_key:
            continue
        shown.append({"title": field.verbose_name,
                      "value": "••••••" if dbviewer.is_secret(field)
                      else (dbviewer.cell(instance, field) if not is_new else "—"),
                      "secret": dbviewer.is_secret(field)})
    fields = [{"field": form[f.name], "computed": dbviewer.is_computed(f),
               "help": f.help_text} for f in dbviewer.editable_fields(model)]
    cascade, blocked = ([], "") if is_new else dbviewer.cascade(instance)
    return render(request, "console/data_row.html", {
        "label": label, "model_name": model._meta.object_name,
        "verbose": model._meta.verbose_name, "instance": instance, "is_new": is_new,
        "title": "New row" if is_new else dbviewer.readable(instance),
        "fields": fields, "read_only": shown, "form": form,
        "cascade": cascade, "blocked": blocked,
        "back": _back(label, request.GET),
    })


@console_required
def row(request, label, pk):
    """One row, every field. Saving runs the model's own validation and its signals."""
    model = _model_or_404(label)
    instance = get_object_or_404(model, pk=pk)
    form_class = dbviewer.form_class(model)

    if request.method == "POST":
        form = form_class(request.POST, instance=instance)
        if form.is_valid():
            changed = dbviewer.changed_fields(form)
            with transaction.atomic():
                form.save()
            dbviewer.forget_counts()
            log.warning("console data: %s edited %s#%s fields=%s",
                        request.platform_admin, label, pk, ",".join(changed) or "none")
            messages.success(request, "Saved%s." % (
                " — " + ", ".join(changed) if changed else ", nothing changed"))
            return redirect(_back(label, request.GET))
        messages.error(request, "Not saved — see the fields marked below.")
    else:
        form = form_class(instance=instance)
    return _row_page(request, model, label, instance, form)


@console_required
def add(request, label):
    """A new row. The same validation as everywhere else, so a half-formed row is refused."""
    model = _model_or_404(label)
    form_class = dbviewer.form_class(model)
    if request.method == "POST":
        form = form_class(request.POST)
        if form.is_valid():
            with transaction.atomic():
                created = form.save()
            dbviewer.forget_counts()
            log.warning("console data: %s added %s#%s", request.platform_admin, label,
                        created.pk)
            messages.success(request, "Added %s." % dbviewer.readable(created))
            return redirect("console_data_row", label=label, pk=created.pk)
        messages.error(request, "Not added — see the fields marked below.")
    else:
        form = form_class()
    return _row_page(request, model, label, None, form)


@console_required
@require_POST
def delete(request, label, pk):
    """Gone for good, with everything that hangs off it. Typing the row's id is the brake."""
    model = _model_or_404(label)
    instance = get_object_or_404(model, pk=pk)
    if instance == request.platform_admin:
        # Deleting your own console login locks you out of the console that holds the button.
        messages.error(request, "That's the login you're signed in with. Nothing was deleted.")
        return redirect("console_data_row", label=label, pk=pk)
    if (request.POST.get("confirm") or "").strip() != str(pk):
        messages.error(request, "Type the row id exactly to delete it. Nothing was deleted.")
        return redirect("console_data_row", label=label, pk=pk)
    name = dbviewer.readable(instance)
    with transaction.atomic():
        removed = instance.delete()
    dbviewer.forget_counts()
    log.warning("console data: %s DELETED %s#%s (%s)", request.platform_admin, label, pk,
                removed)
    messages.success(request, "Deleted %s, and %d row%s that hung off it."
                     % (name, removed[0] - 1, "" if removed[0] == 2 else "s"))
    return redirect(_back(label, None))
