"""Point every existing customer and employee row at the person it belongs to.

Identity is derived, not administered: a row carrying a mobile number IS a person
(identity.py), and the signals in identity_hooks.py keep that true from the moment a row is
saved. Rows written **before** that existed have never been through a save, so they point at
nobody — which is why the console's people screens start out empty on a live database.

This walks them once. It only touches our own app_user column: no SyncUp call is made, so it
is safe to run on a busy day and safe to run again. Opening the app logins is the separate,
slower job that /cron/syncup already does a hundred at a time; --logins starts it here.

    python manage.py link_people            # link the rows, say what happened
    python manage.py link_people --dry-run  # say what would happen, change nothing
    python manage.py link_people --logins   # link, then open logins for one batch
"""
from django.core.management.base import BaseCommand

from ... import appusers, identity
from ...models import AppUser, Customer, Employee


class Command(BaseCommand):
    help = "Link existing customer and employee rows to their person (AppUser)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Count what would be linked without writing anything.")
        parser.add_argument("--logins", action="store_true",
                            help="Also open app logins for one batch (a SyncUp call each).")
        parser.add_argument("--all", action="store_true",
                            help="Re-check every row, not only the ones pointing at nobody.")

    def handle(self, *args, **options):
        dry, every = options["dry_run"], options["all"]
        quiet = options["verbosity"] == 0
        say = (lambda text, style=None: None) if quiet else (
            lambda text, style=None: self.stdout.write(style(text) if style else text))
        before = AppUser.objects.count()
        for model, label in ((Customer, "customer"), (Employee, "employee")):
            rows = model.objects.all() if every else model.objects.filter(app_user__isnull=True)
            linked = skipped = 0
            for row in rows.iterator(chunk_size=500):
                mobile, email = identity.identifiers(row)
                if not mobile and not email:
                    skipped += 1
                    continue
                if dry or identity.attach(row):
                    linked += 1
            say("%-10s %d %s, %d with no usable number"
                % (label + "s:", linked, "would be linked" if dry else "linked", skipped))

        if dry:
            say("Nothing written.", self.style.SUCCESS)
            return
        made = AppUser.objects.count() - before
        say("%d people known (%d new)" % (AppUser.objects.count(), made), self.style.SUCCESS)

        waiting = AppUser.objects.filter(login_status=AppUser.LOGIN_NONE).count()
        if not options["logins"]:
            say("%d have no app login yet. /cron/syncup opens up to %d a run, or run this "
                "again with --logins." % (waiting, appusers.PER_RUN))
            return
        counts = appusers.retry_pending()
        say("Logins: %(created)d opened, %(failed)d failed, %(left)d still waiting" % counts,
            self.style.SUCCESS)
        if counts.get("busy"):
            say("SyncUp asked us to slow down. Run it again in a minute.", self.style.WARNING)
