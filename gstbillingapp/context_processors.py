"""Template context processors for GSTSync.

`asset_version` exposes `ASSET_VER` — a cache-busting token derived from the
modification time of the shared front-end assets (gstsync.css, main.js,
gstable.js). Reference it in templates as `...gstsync.css' %}?v={{ ASSET_VER }}`.

Whenever any of those files changes on disk, `ASSET_VER` changes automatically,
so browsers re-fetch the file — no more manual `?v=N` bumps. This needs no
collectstatic / STATIC_ROOT / manifest, so it is safe for this project's
runserver-served static setup.
"""
import os

from django.conf import settings

# Paths (relative to BASE_DIR) of the assets whose changes should bust the cache.
_ASSET_FILES = (
    'gstbillingapp/static/gstbillingapp/gstsync.css',
    'gstbillingapp/static/gstbillingapp/js/main.js',
    'gstbillingapp/static/gstbillingapp/gstable.js',
    'gstbillingapp/static/gstbillingapp/js/gsearch.js',
)

# Small cache so we don't stat the files on every single request. In DEBUG we
# always recompute (files change during development); in production the value is
# stable until the process restarts (i.e. until a deploy), which is exactly when
# the files can change.
_cached_version = None


def _compute_version():
    latest = 0
    for rel in _ASSET_FILES:
        try:
            mtime = int(os.path.getmtime(os.path.join(settings.BASE_DIR, rel)))
            if mtime > latest:
                latest = mtime
        except OSError:
            pass
    return latest or 1


def asset_version(request):
    global _cached_version
    if settings.DEBUG:
        return {'ASSET_VER': _compute_version()}
    if _cached_version is None:
        _cached_version = _compute_version()
    return {'ASSET_VER': _cached_version}


def syncup_app(request):
    """`SYNCUP_APP` — the SyncUp app's Google Play listing (see syncup_app.listing), or {}
    when no Play URL is set, so `{% if SYNCUP_APP.url %}` hides every app block.

    Lazy: a page that never mentions it costs no query. For a signed-in business it also
    carries `share_wa`, a ready WhatsApp share naming that business."""
    from urllib.parse import quote

    from django.utils.functional import SimpleLazyObject

    def build():
        from .models import SyncUpSettings
        from .syncup_app import listing, share_text
        cfg = SyncUpSettings.load()
        data = listing(cfg)
        if not data:
            return {}
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            prof = getattr(user, "userprofile", None)
            business = ((prof.business_brand or prof.business_title) if prof else None) \
                or user.username
            data["share_wa"] = "https://wa.me/?text=" + quote(
                share_text(cfg, business=business, link=data["business"]))
        return data

    return {'SYNCUP_APP': SimpleLazyObject(build)}
