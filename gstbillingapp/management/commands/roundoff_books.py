"""
One-time / on-demand round-off of customer ledger balances.

Rounds each customer's book balance to the nearest whole rupee (0.50 and above rounds
up, below rounds down) by posting a change_type=3 "Other" adjustment for the leftover
paise — the same mechanism as the books round-off API (book_logs_api_roundoff), applied
in bulk to every customer.

Because the adjustment is only the fractional part (always < ₹1 in magnitude), it is safe
for balances of any size: a customer owing ₹5,000.12 becomes ₹5,000 (Other +0.12), never
zeroed. Balances that are already whole are skipped.

DRY-RUN by default — it only prints what it would do. Pass --commit to actually write.

Examples:
    python manage.py roundoff_books                     # preview ALL businesses
    python manage.py roundoff_books --user goldmedal    # preview one business
    python manage.py roundoff_books --commit            # apply to ALL businesses
"""
import math

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User

from gstbillingapp.models import Book, BookLog
from gstbillingapp.utils import recalculate_book_current_balance


def _round_rupee(x):
    """Nearest whole rupee, 0.50 and above rounding up (matches the invoice round-off)."""
    return float(math.floor(x + 0.5))


class Command(BaseCommand):
    help = ("Round every customer's ledger balance to the nearest whole rupee via an "
            "'Other' adjustment. Dry-run by default; pass --commit to write.")

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true",
                            help="Actually write the adjustments. Without it, this is a dry-run preview.")
        parser.add_argument("--user", dest="user",
                            help="Limit to one business owner (username or numeric id). Default: all businesses.")

    def handle(self, *args, **opts):
        commit = opts["commit"]

        books = Book.objects.select_related("customer", "user").order_by("user_id", "id")
        if opts.get("user"):
            ident = opts["user"]
            owner = (User.objects.filter(pk=ident).first() if str(ident).isdigit()
                     else User.objects.filter(username=ident).first())
            if not owner:
                raise CommandError(f"No business owner matched '{ident}' (username or id).")
            books = books.filter(user=owner)
            self.stdout.write(f"Scope: {owner.username} (user #{owner.id})")
        else:
            self.stdout.write("Scope: ALL businesses")

        self.stdout.write(self.style.WARNING("DRY-RUN — no changes will be written. Pass --commit to apply.")
                          if not commit else self.style.WARNING("COMMIT — writing adjustments."))

        adjusted = skipped = 0
        net_delta = 0.0
        for book in books.iterator():
            bal = round(float(book.current_balance or 0), 2)
            rounded = _round_rupee(bal)
            delta = round(rounded - bal, 2)
            if abs(delta) < 0.005:          # already a whole rupee — nothing to do
                skipped += 1
                continue

            name = book.customer.customer_name if book.customer else f"book#{book.id}"
            self.stdout.write(f"  {name[:34]:34}  {bal:>12.2f}  ->  {rounded:>12.2f}   (Other {delta:+.2f})")
            adjusted += 1
            net_delta += delta

            if commit:
                BookLog.objects.create(
                    parent_book=book,
                    change_type=3,               # Other
                    change=delta,
                    description="Round-off adjustment",
                )
                recalculate_book_current_balance(book)

        self.stdout.write("")
        verb = "Rounded" if commit else "Would round"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {adjusted} book(s); {skipped} already whole. "
            f"Net 'Other' adjustment: {net_delta:+.2f}"))
        if not commit and adjusted:
            self.stdout.write("Re-run with --commit to apply these adjustments.")
