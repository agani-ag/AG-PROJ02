"""Create (or manage) a platform admin — the login that can reach /console/.

Deliberately a command and not a console screen: the FIRST admin has to come from
somewhere, and requiring server access to mint console access means a compromised console
session can never quietly create a second way in.

A platform admin is NOT a business. It has no row in auth_user, no UserProfile, and never
appears in the console's business list — the two populations live in different tables.

The password is generated here and printed ONCE. It is stored only as a hash, so it
cannot be recovered afterwards; if it is lost, generate a new one with --reset-password.
The admin can change it themselves at /console/password.

Examples:
    python manage.py create_platform_admin ganesh
    python manage.py create_platform_admin ganesh --name "Ganesh S"
    python manage.py create_platform_admin ganesh --reset-password
    python manage.py create_platform_admin ganesh --revoke
    python manage.py create_platform_admin ganesh --password-stdin < secret.txt
"""
import sys

from django.core.management.base import BaseCommand, CommandError

from gstbillingapp.models import PlatformAdmin
from gstbillingapp.passwords import generate_password  # noqa: F401 (tests import it here)


class Command(BaseCommand):
    help = ("Create or manage a platform admin for the /console/ operator console. "
            "Generates the password and prints it once.")

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--name", default=None, help="Display name shown in the console.")
        parser.add_argument("--reset-password", action="store_true",
                            help="Generate a new password for an existing admin.")
        parser.add_argument("--password-stdin", action="store_true",
                            help="Read a password from stdin instead of generating one.")
        parser.add_argument("--revoke", action="store_true",
                            help="Revoke console access without deleting the record.")
        parser.add_argument("--restore", action="store_true", help="Undo --revoke.")

    def handle(self, *args, **opts):
        username = opts["username"].strip()
        if not username:
            raise CommandError("Username is required.")

        admin = PlatformAdmin.objects.filter(username=username).first()

        # --- revoke / restore -------------------------------------------------
        if opts["revoke"] or opts["restore"]:
            if admin is None:
                raise CommandError("'%s' is not a platform admin." % username)
            admin.is_active = bool(opts["restore"])
            admin.save(update_fields=["is_active"])
            self.stdout.write(self.style.SUCCESS("'%s' console access %s." % (
                username, "restored" if admin.is_active else "revoked")))
            return

        if admin and not opts["reset_password"]:
            raise CommandError(
                "'%s' is already a platform admin. Use --reset-password for a new password."
                % username)
        if admin is None and opts["reset_password"]:
            raise CommandError("'%s' is not a platform admin yet." % username)

        # --- password ---------------------------------------------------------
        if opts["password_stdin"]:
            password = sys.stdin.readline().rstrip("\n")
            if not password:
                raise CommandError("No password on stdin.")
            generated = False
        else:
            password = generate_password()
            generated = True

        if admin is None:
            admin = PlatformAdmin(username=username, full_name=opts["name"] or username)
        elif opts["name"]:
            admin.full_name = opts["name"]
        admin.is_active = True
        admin.set_password(password)      # hashed here; the raw value is never stored
        admin.save()

        self._report(username, password, generated, opts["reset_password"])

    def _report(self, username, password, generated, was_reset):
        w = self.stdout.write
        w("")
        w(self.style.SUCCESS("  %s platform admin" % ("Reset" if was_reset else "Created")))
        w("")
        w("    Console    /console/login")
        w("    Username   %s" % username)
        w("    Password   %s" % self.style.WARNING(password))
        w("")
        if generated:
            w("  This password is shown ONCE — only its hash is stored, so it cannot be")
            w("  recovered later. Copy it now.")
            w("  Change it any time from /console/password, or run this command again")
            w("  with --reset-password to issue a new one.")
        w("")
