"""The ads page — its own corner of the site.

Ads do not belong on the signed-in app: those screens show a business's customers, balances
and invoices, and a third-party script there is both a privacy question and weight the
dashboard doesn't need (base.html is already heavy). So this is one standalone public page
with its own light template, and nothing it loads touches the rest of the site.

Ownership is proved with the `google-adsense-account` meta tag rather than an ads.txt file.
Google looks for that tag on the site's **home page**, so it is rendered there too — it is
inert markup, no script and no weight, which is why it can sit on a page the ads never do.
"""
from django.conf import settings
from django.shortcuts import render


def publisher_id():
    """The AdSense publisher id, or "" when ads are switched off."""
    return (getattr(settings, "ADSENSE_PUBLISHER_ID", "") or "").strip()


def ads_page(request):
    """The page the ads live on. Public, so Google's crawler can actually read it."""
    return render(request, "ads.html", {"adsense_pub": publisher_id()})
