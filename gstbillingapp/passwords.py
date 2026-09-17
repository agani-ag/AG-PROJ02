"""Password generation for credentials GSTSync issues itself.

Two callers with different readers:

  * console admins — read off a terminal by an operator, so long and strong;
  * customer app logins — typed on a phone by a shop owner, who can change it in the app,
    so shorter and without symbols.

Both avoid look-alike characters (0/O, 1/l/I), because every one of these passwords is
read by a person and typed somewhere else.
"""
import secrets

_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_LOWER = "abcdefghijkmnopqrstuvwxyz"
_DIGITS = "23456789"
_SYMBOLS = "!@#$%&*?"


def generate_password(length=18, symbols=True):
    """A random password with at least one upper-case letter, lower-case letter and digit."""
    alphabet = _UPPER + _LOWER + _DIGITS + (_SYMBOLS if symbols else "")
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.isupper() for c in pw) and any(c.islower() for c in pw)
                and any(c.isdigit() for c in pw)):
            return pw


def generate_customer_password():
    """For a shop owner's app login: 10 characters, letters and digits only."""
    return generate_password(length=10, symbols=False)
