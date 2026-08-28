"""One-time backfill: strip the stored whitespace out of invoice_json / quotation_json.

Both blobs were written with a bare json.dumps(), whose default separators are ', ' and
': '. That padding is roughly 6% of every invoice, and invoice_json alone is ~60% of the
database. Re-serialising with compact separators stores exactly the same object with no
padding.

Every row is verified before it is written: the minified text is parsed back and compared
to the original object, and a row is only saved when they are identical. A row that does
not round-trip (or does not parse at all) is reported and left untouched.

The write paths were fixed at the same time (utils.json_compact), so this is a one-off —
new invoices are already stored compact.

DRY-RUN by default. Pass --commit to write.

Examples:
    python manage.py minify_invoice_json               # preview the saving
    python manage.py minify_invoice_json --commit      # apply
"""
import json

from django.core.management.base import BaseCommand
from django.db import transaction

from gstbillingapp.models import Invoice, Quotation


TARGETS = (
    ("Invoice", Invoice, "invoice_json"),
    ("Quotation", Quotation, "quotation_json"),
)


class Command(BaseCommand):
    help = ("Re-serialise stored invoice/quotation JSON without whitespace padding. "
            "Dry-run by default; pass --commit to write.")

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true",
                            help="Actually write. Without it, this only reports what would change.")

    def handle(self, *args, **opts):
        commit = opts["commit"]
        grand_before = grand_after = 0
        grand_rows = grand_skipped = 0

        for label, model, field in TARGETS:
            before = after = 0
            changed = []
            skipped = []

            for pk, raw in model.objects.values_list("pk", field):
                if not raw:
                    continue
                before += len(raw)
                try:
                    obj = json.loads(raw)
                except ValueError:
                    skipped.append((pk, "unparseable"))
                    after += len(raw)
                    continue
                mini = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
                # Verify losslessness on this exact row before considering a write.
                try:
                    if json.loads(mini) != obj:
                        skipped.append((pk, "round-trip differs"))
                        after += len(raw)
                        continue
                except ValueError:
                    skipped.append((pk, "round-trip unparseable"))
                    after += len(raw)
                    continue
                after += len(mini)
                if mini != raw:
                    changed.append((pk, mini))

            saved = before - after
            self.stdout.write(self.style.MIGRATE_HEADING(
                "%s.%s" % (label, field)))
            self.stdout.write(
                "  rows %d   would rewrite %d   skipped %d" % (
                    model.objects.exclude(**{field: ""}).count(), len(changed), len(skipped)))
            self.stdout.write(
                "  %.1f KB -> %.1f KB   saves %.1f KB (%.1f%%)" % (
                    before / 1024.0, after / 1024.0, saved / 1024.0,
                    (100.0 * saved / before) if before else 0.0))
            for pk, why in skipped[:10]:
                self.stdout.write(self.style.WARNING("  ! pk=%s %s" % (pk, why)))
            if len(skipped) > 10:
                self.stdout.write(self.style.WARNING("  ! ...and %d more" % (len(skipped) - 10)))

            if commit and changed:
                with transaction.atomic():
                    for pk, mini in changed:
                        model.objects.filter(pk=pk).update(**{field: mini})
                self.stdout.write(self.style.SUCCESS("  wrote %d rows" % len(changed)))

            grand_before += before
            grand_after += after
            grand_rows += len(changed)
            grand_skipped += len(skipped)

        total = grand_before - grand_after
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("total"))
        self.stdout.write("  rows to rewrite %d   skipped %d" % (grand_rows, grand_skipped))
        self.stdout.write("  saves %.1f KB" % (total / 1024.0))
        if not commit:
            self.stdout.write(self.style.WARNING(
                "  DRY-RUN — nothing written. Re-run with --commit to apply."))
        else:
            self.stdout.write(self.style.SUCCESS(
                "  committed. Run `manage.py cleanup_db --backup --vacuum` to reclaim the space."))
