"""Indian-style money formatting for the mobile (and other) templates."""
import re

from django import template

register = template.Library()


def format_inr(value, decimals=2):
    """Format a number with Indian digit grouping (lakh/crore), e.g. 3123589.5 -> 31,23,589.50.

    Returns a plain string (no currency symbol). Bad input -> "0".
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "0"

    neg = value < 0
    value = abs(value)

    if decimals:
        whole, frac = f"{value:.{decimals}f}".split(".")
    else:
        whole, frac = f"{value:.0f}", None

    if len(whole) > 3:
        last3 = whole[-3:]
        rest = whole[:-3]
        # Group the remaining digits in twos from the right (Indian system).
        rest = re.sub(r"(?<=\d)(?=(?:\d\d)+$)", ",", rest)
        grouped = rest + "," + last3
    else:
        grouped = whole

    out = grouped + ("." + frac if frac is not None else "")
    return "-" + out if neg else out


@register.filter(name="inr")
def inr(value):
    """Two-decimal Indian format: {{ amount|inr }} -> 31,23,589.02"""
    return format_inr(value, decimals=2)


@register.filter(name="inr0")
def inr0(value):
    """Whole-rupee Indian format: {{ amount|inr0 }} -> 31,23,589"""
    return format_inr(value, decimals=0)


def format_inr_smart(value):
    """Indian format that drops a whole-rupee's .00 but KEEPS real paise on historical
    values: 29800.0 -> '29,800', 29857.49 -> '29,857.49'."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "0"
    if abs(v - round(v)) < 0.005:        # effectively a whole rupee
        return format_inr(v, decimals=0)
    return format_inr(v, decimals=2)


@register.filter(name="inrs")
def inrs(value):
    """Smart Indian money: whole rupees show no decimals, real paise are kept.
    {{ amount|inrs }} -> 29,800  or  29,857.49"""
    return format_inr_smart(value)


@register.filter
def initials(value, count=2):
    """Teams-style initials: first letter of each of the first `count` words
    (default 2), upper-cased. Single-word names fall back to their first `count`
    letters.  "AMMAN HARDWARE" -> "AH", "A.M VIKASH TRADERS" -> "AV", "ALPHA" -> "AL"."""
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = 2
    if not value:
        return ''
    words = [w for w in str(value).strip().split() if w]
    if not words:
        return ''
    if len(words) == 1:
        return words[0][:count].upper()
    return ''.join(w[0] for w in words[:count]).upper()


from django.utils.html import escape
from django.utils.safestring import mark_safe


@register.simple_tag(takes_context=True)
def sort_th(context, key, label, align=''):
    """Render a sortable <th> that toggles ?sort=<key> / ?sort=-<key> and shows an
    arrow, preserving all other query params (search/filters). The VIEW must read
    ?sort and order its queryset accordingly.

        {% sort_th 'amount' 'Amount' 'r' %}
    """
    request = context.get('request')
    cur = (request.GET.get('sort') if request else '') or ''
    nxt = '-' + key if cur == key else key
    arrow = ''
    if cur == key:
        arrow = ' <i class="fas fa-arrow-up gico"></i>'
    elif cur == '-' + key:
        arrow = ' <i class="fas fa-arrow-down gico"></i>'
    params = request.GET.copy() if request else {}
    if params:
        params.pop('page', None)
        params.pop('sort', None)
    rest = params.urlencode() if params else ''
    href = '?sort=' + nxt + (('&' + rest) if rest else '')
    cls = (' class="' + align + '"') if align else ''
    return mark_safe('<th%s><a href="%s">%s%s</a></th>' % (cls, escape(href), escape(str(label)), arrow))
