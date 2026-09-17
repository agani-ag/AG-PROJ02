"""Database maintenance from the command line.

The same code the /cron/ endpoints run (gstbillingapp/cleanup.py), exposed as a command
so you can test it, run it by hand, or drive it from a shell cron if you ever move off
the HTTP cron service.

Expired sessions are always purged. Quotations only with --quotations, and then every
status once past the window (see cleanup.purge_quotations). No invoice, booklog or
inventorylog is ever touched.

Examples:
    python manage.py cleanup_db --stats                    # report only, changes nothing
    python manage.py cleanup_db                            # purge expired sessions
    python manage.py cleanup_db --quotations 15 --dry-run  # preview the quotation purge
    python manage.py cleanup_db --backup                   # compacted copy, prune to keep
    python manage.py cleanup_db --backup --vacuum --quotations 15   # the one-job cron
"""
import json

from django.core.management.base import BaseCommand

from gstbillingapp.cleanup import (
    LockBusy, db_stats, job_lock, purge_quotations, run_backup, run_cleanup,
)


class Command(BaseCommand):
    help = ("Purge expired sessions, optionally back up (VACUUM INTO) and compact the "
            "database. Same code path as the /cron/ endpoints.")

    def add_arguments(self, parser):
        parser.add_argument("--stats", action="store_true",
                            help="Report database size / sessions / backups and exit. Changes nothing.")
        parser.add_argument("--backup", action="store_true",
                            help="Write a compacted backup copy and prune to DB_BACKUP_KEEP.")
        parser.add_argument("--vacuum", action="store_true",
                            help="Also VACUUM in place. Needs a backup from the last 48h.")
        parser.add_argument("--keep", type=int, default=None,
                            help="Override how many backups to retain for this run.")
        parser.add_argument("--quotations", type=int, default=None, metavar="DAYS",
                            help="Delete ALL quotations older than DAYS, any status. Omit to touch none.")
        parser.add_argument("--dry-run", action="store_true",
                            help="With --quotations, show what would be deleted without deleting.")

    def handle(self, *args, **opts):
        if opts["stats"]:
            self._dump("stats", db_stats())
            return

        if opts["dry_run"]:
            if opts["quotations"] is None:
                self.stdout.write(self.style.WARNING("--dry-run needs --quotations DAYS"))
            else:
                self._dump("quotations (dry-run)",
                           purge_quotations(opts["quotations"], commit=False))
            return

        if opts["backup"]:
            try:
                with job_lock("backup"):
                    self._dump("backup", run_backup(keep=opts["keep"]))
            except LockBusy:
                self.stdout.write(self.style.WARNING("backup: another run is in progress — skipped"))

        try:
            with job_lock("cleanup"):
                self._dump("cleanup", run_cleanup(vacuum=opts["vacuum"],
                                                  quotation_days=opts["quotations"]))
        except LockBusy:
            self.stdout.write(self.style.WARNING("cleanup: another run is in progress — skipped"))

    def _dump(self, label, data):
        self.stdout.write(self.style.MIGRATE_HEADING(label))
        for line in json.dumps(data, indent=2, sort_keys=True).splitlines():
            self.stdout.write("  " + line)
