"""GSTIN helpers — normalise, and validate format plus the check character.

A GSTIN is 15 characters: a 2-digit state code, the holder's 10-character PAN, an entity
number, the letter Z, and a check character computed from the first 14 (mod-36, alternating
weights 1 and 2). The check character is what lets us tell a real GSTIN from a typo —
`…K1ZO` (letter O) and `…K1Z0` (digit zero) look alike, and only one passes.

Used to decide which GSTINs may serve as evidence that two customer rows are the same
shop owner. It never blocks data entry by itself.
"""
import re

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_FORMAT = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def normalise_gstin(value):
    """Upper-case with every space removed."""
    return "".join((value or "").split()).upper()


def gstin_check_char(first14):
    """The check character a GSTIN with these first 14 characters must end in."""
    total = 0
    for i, ch in enumerate(first14):
        product = _ALPHABET.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return _ALPHABET[(36 - total % 36) % 36]


def is_valid_gstin(value):
    """True only for a well-formed GSTIN whose check character is correct.

    State code 00 does not exist, so it is rejected too — that catches placeholder values
    typed just to fill the field, such as 00AAAAA0000A0A0.
    """
    g = normalise_gstin(value)
    if not _FORMAT.match(g) or g[:2] == "00":
        return False
    return gstin_check_char(g[:14]) == g[14]
