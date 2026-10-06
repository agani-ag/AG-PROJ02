"""The rules behind the console's Data screens — which tables, which fields, what's refused.

The console can read and change any row in the database. That is deliberate: when a number is
wrong in a way no screen can reach, somebody has to be able to fix it. What this module does is
decide *how much rope* that comes with:

  * **secrets are never shown and never accepted** — a password hash, the SyncUp partner key, a
    passkey digest or a device token is rendered as dots and dropped from the form, so the page
    can't leak one and can't overwrite one with plain text;
  * **fields the app maintains carry a warning** — a balance, a token version, a login status.
    They stay editable, because repairing one is half the point, but nobody should change one
    by accident;
  * **saving goes through the model**, so `full_clean()` and every signal run exactly as they
    do on the business screens. Editing a customer's number here re-links their person and
    reaches SyncUp, the same as if their shop had typed it.

Nothing here changes the schema. There is no way to add a column, drop a table or run a
migration: the models decide what exists, and this only moves data between them.
"""
from django import forms
from django.apps import apps
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import models as dj
from django.db.models.deletion import Collector, ProtectedError
from django.db.models.functions import Cast
from django.forms import modelform_factory

# Never rendered, never written. Matched on the exact field name — "token_version" is an
# ordinary integer and stays editable, "token" is somebody's session and does not.
SECRET_FIELDS = {"password", "partner_key", "signing_secret", "digest", "token", "api_key",
                 "secret", "passkey"}

# Editable, but the app writes these itself: changing one by hand overrides bookkeeping.
COMPUTED_FIELDS = {"current_balance", "token_version", "mobile_token_version", "link_keys",
                   "login_status", "login_issued_at", "app_user", "syncup_active",
                   "syncup_synced_at", "identity_pending", "connection", "share_code",
                   "dedupe_key", "app_opens", "last_open_at"}

# A foreign key to a table bigger than this gets a plain id box instead of a dropdown with
# ten thousand options in it.
FK_SELECT_MAX = 200

PAGE_SIZE = 50
COUNT_CACHE_SECONDS = 300

# The order the tables are shown in — the work they belong to, not the alphabet. Anything not
# listed still appears, under "Other", so a model added later is never invisible.
GROUPS = (
    ("Billing & money", ("Invoice", "Quotation", "Book", "BookLog", "ChequeLeaf",
                         "BalanceConfirmation", "ExpenseTracker", "VendorPurchase",
                         "PurchaseLog")),
    ("People", ("AppUser", "Customer", "Employee", "EmployeePosting", "EmployeeIncentive",
                "AttendanceLog", "SalaryRecord")),
    ("Stock & catalogue", ("Product", "ProductCategory", "Inventory", "InventoryLog",
                           "Asset", "AssetLog")),
    ("Businesses", ("User", "UserProfile", "BankDetails", "BusinessNotifications",
                    "BusinessPasskey", "ActiveDevice")),
    ("SyncUp", ("SyncUpSettings", "SyncUpMessage", "SyncUpJobRun")),
    ("Telegram", ("BusinessTelegram", "TelegramChat", "TelegramReport")),
    ("Surveys", ("Survey", "SurveyQuestion", "SurveyResponse", "SurveyAnswer")),
    ("Console", ("PlatformAdmin",)),
)


# --------------------------------------------------------------------------- #
# Which tables
# --------------------------------------------------------------------------- #
def label_of(model):
    """The name a URL carries, e.g. "gstbillingapp.customer"."""
    return "%s.%s" % (model._meta.app_label, model._meta.model_name)


def all_models():
    """Every table the console may touch: our own, plus the business login table."""
    return list(apps.get_app_config("gstbillingapp").get_models()) + [User]


def find(label):
    """The model for a URL label, or None — never trust the label to name a real table."""
    return next((m for m in all_models() if label_of(m) == (label or "").lower()), None)


def groups():
    """[(title, [model, ...])] in the order above, with anything unlisted under "Other"."""
    by_name = {m._meta.object_name: m for m in all_models()}
    out, placed = [], set()
    for title, names in GROUPS:
        found = [by_name[n] for n in names if n in by_name]
        placed.update(m._meta.object_name for m in found)
        if found:
            out.append((title, found))
    rest = [m for m in all_models() if m._meta.object_name not in placed]
    if rest:
        out.append(("Other", sorted(rest, key=lambda m: m._meta.object_name)))
    return out


def row_count(model):
    """Cached, because the table list would otherwise count 39 tables on every load."""
    key = "dbviewer:count:" + label_of(model)
    value = cache.get(key)
    if value is None:
        value = model._default_manager.count()
        cache.set(key, value, COUNT_CACHE_SECONDS)
    return value


def forget_counts():
    """After a write, the number on the table list is stale."""
    cache.delete_many(["dbviewer:count:" + label_of(m) for m in all_models()])


# --------------------------------------------------------------------------- #
# Which fields
# --------------------------------------------------------------------------- #
def is_secret(field):
    return field.name.lower() in SECRET_FIELDS


def is_computed(field):
    return field.name.lower() in COMPUTED_FIELDS


def fields_of(model):
    """Every stored column, in the order the model declares them."""
    return list(model._meta.concrete_fields)


def editable_fields(model):
    return [f for f in fields_of(model)
            if f.editable and not f.primary_key and not is_secret(f)]


def columns(model):
    """Every column, key first — the grid shows the whole row and scrolls sideways, the way a
    database browser does. Nothing is dropped; long values are shortened per cell."""
    key = [f for f in fields_of(model) if f.primary_key]
    return key + [f for f in fields_of(model) if not f.primary_key]


# The table picker: one flat list, no groups — the point of the screen is to get to a table
# in one click, not to be taught how the schema is organised.
def choices():
    """[(label, "Customer", 219)] for every table, alphabetically."""
    return sorted(((label_of(m), m._meta.object_name, row_count(m)) for m in all_models()),
                  key=lambda row: row[1].lower())


def default_label():
    """What the screen opens on when nothing is picked."""
    for wanted in ("gstbillingapp.customer", "gstbillingapp.invoice"):
        if find(wanted) is not None:
            return wanted
    models = all_models()
    return label_of(models[0]) if models else ""


def cell(row, field):
    """One value, short enough for a table cell and never a secret."""
    if is_secret(field):
        return "••••••"
    if isinstance(field, dj.ForeignKey):
        target = getattr(row, field.name, None)
        return "%s #%s" % (target, target.pk) if target is not None else "—"
    value = getattr(row, field.attname, None)
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value)
    return text if len(text) <= 60 else text[:57] + "…"


def readable(row):
    """A row's own name, for a heading."""
    try:
        text = str(row)
    except Exception:                               # noqa: BLE001 — a broken __str__ is data
        text = ""
    return text or "%s #%s" % (type(row)._meta.object_name, row.pk)


# --------------------------------------------------------------------------- #
# The form
# --------------------------------------------------------------------------- #
def form_class(model):
    """A form over everything editable, with the console's own widgets.

    A fresh class each call, so tightening a widget here can't leak into another request."""
    names = [f.name for f in editable_fields(model)]
    form = modelform_factory(model, fields=names)
    for name, field in form.base_fields.items():
        model_field = model._meta.get_field(name)
        if isinstance(model_field, dj.ForeignKey) and \
                row_count(model_field.related_model) > FK_SELECT_MAX:
            # Too many rows to list: take the id, and let the field still prove it exists.
            field.widget = forms.NumberInput()
        if isinstance(model_field, (dj.TextField, dj.JSONField)):
            field.widget = forms.Textarea(attrs={"rows": 5})
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            continue
        widget.attrs["class"] = (widget.attrs.get("class", "") + " control").strip()
    return form


def changed_fields(form):
    """What the save actually moved — for the log line."""
    return sorted(form.changed_data)


# --------------------------------------------------------------------------- #
# Searching, filtering, deleting
# --------------------------------------------------------------------------- #
TRUE_WORDS = {"1", "true", "t", "yes", "y", "on"}
FALSE_WORDS = {"0", "false", "f", "no", "n", "off"}
COMPARISONS = ((">=", "__gte"), ("<=", "__lte"), (">", "__gt"), ("<", "__lt"))

# Casting a column to text to match part of it can't use an index, so "any column" only
# reaches past the text columns on a table small enough for a scan to be cheap.
CAST_SCAN_MAX = 50000


def _text_fields(model):
    return [f for f in model._meta.concrete_fields
            if isinstance(f, (dj.CharField, dj.TextField)) and not is_secret(f)]


def text_paths(model, prefix="", depth=2, limit=8):
    """Where a readable word can live on this model — following a foreign key when the table
    holds none of its own.

    A book log's `parent_book` is a Book, and a Book has no words at all: its name on screen
    comes from its customer. Typing "ambal" there has to reach `parent_book__customer__
    customer_name`, or the filter does nothing and looks broken."""
    paths = [prefix + f.name for f in _text_fields(model)]
    if paths or depth <= 1:
        return paths[:limit]
    for field in model._meta.concrete_fields:
        if len(paths) >= limit:
            break
        if isinstance(field, dj.ForeignKey) and field.related_model is not model:
            paths += text_paths(field.related_model, prefix + field.name + "__",
                                depth - 1, limit)
    return paths[:limit]


def _as_text(name):
    """(alias, annotation) — the column as a string, so part of a number or a date matches."""
    alias = "_f_" + name.replace("__", "_")
    return alias, Cast(name, dj.TextField())


def _typed_lookup(field, value):
    """A comparison or an exact match for a column that isn't text, or None if the value
    isn't one the column could hold. ">500" and "<=2026-01-01" both work."""
    for sign, suffix in COMPARISONS:
        if value.startswith(sign):
            try:
                return {field.name + suffix: field.to_python(value[len(sign):].strip())}
            except Exception:                       # noqa: BLE001 — a typo, not a crash
                return None
    if isinstance(field, dj.BooleanField):
        if value.lower() in TRUE_WORDS:
            return {field.name: True}
        if value.lower() in FALSE_WORDS:
            return {field.name: False}
        return None
    try:
        return {field.name: field.to_python(value)}
    except Exception:                               # noqa: BLE001
        return None


def _column_clause(field, value):
    """(Q, annotations) for one filter box — whatever that column can usefully mean."""
    if isinstance(field, dj.ForeignKey):
        key = value[1:] if value.startswith("#") else value
        if key.isdigit():
            return dj.Q(**{field.name + "_id": int(key)}), {}
        where = dj.Q()
        for path in text_paths(field.related_model, field.name + "__"):
            where |= dj.Q(**{path + "__icontains": value})
        if where:
            return where, {}
        alias, annotation = _as_text(field.name)    # nothing readable behind it: match the id
        return dj.Q(**{alias + "__icontains": value}), {alias: annotation}
    if isinstance(field, (dj.CharField, dj.TextField)):
        return dj.Q(**{field.name + "__icontains": value}), {}
    lookup = _typed_lookup(field, value)
    if lookup is not None:
        return dj.Q(**lookup), {}
    alias, annotation = _as_text(field.name)        # "27" inside -275.00, "2026-09" in a date
    return dj.Q(**{alias + "__icontains": value}), {alias: annotation}


def _any_clause(model, q):
    """(Q, annotations) for the one box that searches the whole row."""
    where, casts = dj.Q(), {}
    for path in [f.name for f in _text_fields(model)]:
        where |= dj.Q(**{path + "__icontains": q})
    for field in model._meta.concrete_fields:
        if isinstance(field, dj.ForeignKey):
            for path in text_paths(field.related_model, field.name + "__"):
                where |= dj.Q(**{path + "__icontains": q})
    if q.isdigit():
        where |= dj.Q(pk=q)
    if row_count(model) <= CAST_SCAN_MAX:
        for field in model._meta.concrete_fields:
            if field.primary_key or is_secret(field) or field.is_relation or \
                    isinstance(field, (dj.CharField, dj.TextField)):
                continue
            alias, annotation = _as_text(field.name)
            casts[alias] = annotation
            where |= dj.Q(**{alias + "__icontains": q})
    return where, casts


def apply_filters(model, rows, params):
    """Narrow a table by the one box at the top and the box under each column.

    Returns (rows, what_was_typed, narrowed). Every column can be filtered: text matches
    anywhere, a foreign key takes an id or a word from the row it points at, numbers and
    dates take an exact value or a comparison, and anything else is matched as text."""
    typed, casts, where = {}, {}, dj.Q()
    for field in fields_of(model):
        value = (params.get("f_" + field.name) or "").strip()
        if not value or is_secret(field):
            continue
        typed[field.name] = value
        clause, extra = _column_clause(field, value)
        casts.update(extra)
        where &= clause
    q = (params.get("q") or "").strip()
    if q:
        clause, extra = _any_clause(model, q)
        casts.update(extra)
        where &= clause
    if casts:
        rows = rows.annotate(**casts)
    if where:
        rows = rows.filter(where)
    return rows, typed, bool(q or typed)


def cascade(row):
    """What this row takes with it, and what it leaves behind. (list, blocked_message).

    Two different fates, and the second one is the quiet danger: a link set to SET_NULL
    doesn't delete the other row, it empties the column. A customer's books survive their
    customer — pointing at nobody."""
    collector = Collector(using=row._state.db or "default")
    try:
        collector.collect([row])
    except ProtectedError as e:
        return [], "Another row points at this one and must go first: %s" % e
    out = []
    for model, instances in collector.data.items():
        count = len(instances)
        if model is type(row) and count == 1:
            continue
        out.append({"name": model._meta.verbose_name_plural.title(), "count": count,
                    "kind": "deleted"})
    for (field, _value), batches in collector.field_updates.items():
        count = sum(len(list(batch)) for batch in batches)
        if count:
            out.append({"name": "%s.%s" % (field.model._meta.object_name, field.name),
                        "count": count, "kind": "emptied"})
    return sorted(out, key=lambda r: -r["count"]), ""
