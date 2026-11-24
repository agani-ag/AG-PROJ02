"""Closing the console's notice.

The only thing the business side does with a notice is put it away. That is remembered in
the session rather than the database: it should come back the next time they sign in, and
nothing about one person's dismissal is worth a row.
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from ..models import ConsoleNotice


@login_required
@require_POST
def close(request):
    """Put the notice away for this browser session. The corner button still reopens it."""
    notice = ConsoleNotice.live()
    if notice is not None:
        request.session[notice.seen_key] = True
    return JsonResponse({"status": "ok"})
