from django.http import Http404, HttpResponse
from django.shortcuts import render


# Paths that talk to machines rather than people. A 404 under these stays a BARE 404:
#
#   * /cron/  — those endpoints answer 404 on a bad or missing key specifically so they
#     look like nothing is there. Returning a branded HTML page instead announces the
#     application to anyone scanning, and ships several KB to a cron service on every
#     unauthorised poll.
#   * anything with /api/ — a caller expecting JSON should get a status code, not a
#     styled page it then has to fail to parse.
#   * /static/ and /media/ — a missing asset must not return an HTML document; the
#     browser would try to parse the 404 page as CSS, JS or an image.
_BARE_PREFIXES = ("/cron/", "/static/", "/media/")
_BARE_MARKERS = ("/api/",)


def _wants_error_page(request):
    path = request.path or ""
    if path.startswith(_BARE_PREFIXES):
        return False
    return not any(marker in path for marker in _BARE_MARKERS)


class Custom404Middleware:
    """Render the branded 404 page for missing PAGES, even when DEBUG is on.

    Django only uses 404.html when DEBUG is False; with DEBUG on it shows the yellow
    URLconf debug page instead. This middleware makes the real page visible in both, so
    what is developed is what ships.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code != 404:
            return response

        if _wants_error_page(request):
            return render(request, '404.html', status=404)

        # Django's OWN 404 handler already rendered this template — page_not_found()
        # picks up any template named 404.html — so for a machine-facing path it is not
        # enough to decline; the branded HTML is already in the response and has to be
        # replaced. Only text/html is stripped, so a view that deliberately returned a
        # JSON 404 body keeps it.
        if response.get("Content-Type", "").startswith("text/html"):
            return HttpResponse(status=404)
        return response

    def process_exception(self, request, exception):
        """Handle Http404 raised from a view."""
        if isinstance(exception, Http404):
            if not _wants_error_page(request):
                return HttpResponse(status=404)
            return render(request, '404.html', status=404)
        return None
