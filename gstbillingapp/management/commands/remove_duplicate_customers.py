from django.core.management.base import BaseCommand
from django.db.models import Count, Sum
from django.db import transaction
from gstbillingapp.models import Customer, Book, BookLog, Invoice, Quotation


class Command(BaseCommand):
    help = 'Remove duplicate customers while preserving books, invoices, and balance information'

    def handle(self, *args, **options):
        # Find duplicates based on user + customer_name
        duplicates = Customer.objects.values('user', 'customer_name').annotate(
            count=Count('id')
        ).filter(count__gt=1)

        total_removed = 0
        total_groups = len(duplicates)
        total_books_merged = 0
        total_book_logs_merged = 0
        total_invoices_merged = 0
        total_quotations_merged = 0

        self.stdout.write(f"Found {total_groups} groups of duplicate customers")

        for dup in duplicates:
            user_id = dup['user']
            customer_name = dup['customer_name']
            
            # Get all customers with same user and name
            customers = Customer.objects.filter(
                user_id=user_id, 
                customer_name=customer_name
            ).order_by('-id')

            # Keep the first (most recent) and merge the rest
            customers_to_delete = list(customers[1:])
            keeper = customers[0]
            
            self.stdout.write(f"\nProcessing: {customer_name} (User: {user_id})")
            self.stdout.write(f"  Keeping Customer ID: {keeper.id}")
            
            with transaction.atomic():
                total_balance = 0
                
                for customer in customers_to_delete:
                    # Count and merge book logs
                    book_logs_count = BookLog.objects.filter(
                        parent_book__customer=customer
                    ).count()
                    if book_logs_count > 0:
                        self.stdout.write(f"  - Found {book_logs_count} book logs for Customer ID: {customer.id}")
                        total_book_logs_merged += book_logs_count
                    
                    # Get all books for this duplicate customer
                    duplicate_books = Book.objects.filter(customer=customer)
                    
                    for dup_book in duplicate_books:
                        self.stdout.write(f"    - Merging Book ID: {dup_book.id} (Balance: {dup_book.current_balance})")
                        total_balance += dup_book.current_balance
                        
                        # Check if keeper already has a book
                        keeper_book = Book.objects.filter(customer=keeper, user=keeper.user).first()
                        
                        if keeper_book:
                            # Transfer all book logs to keeper's book
                            BookLog.objects.filter(parent_book=dup_book).update(parent_book=keeper_book)
                            self.stdout.write(f"      ✓ Transferred logs to existing Book ID: {keeper_book.id}")
                        else:
                            # Transfer the book itself to keeper
                            dup_book.customer = keeper
                            dup_book.save()
                            keeper_book = dup_book
                            self.stdout.write(f"      ✓ Transferred Book ID: {dup_book.id} to keeper")
                        
                        # Delete the duplicate book if it was merged
                        if dup_book.id != keeper_book.id:
                            dup_book.delete()
                            total_books_merged += 1
                    
                    # Update invoices to point to keeper
                    invoice_count = Invoice.objects.filter(invoice_customer=customer).count()
                    if invoice_count > 0:
                        Invoice.objects.filter(invoice_customer=customer).update(invoice_customer=keeper)
                        self.stdout.write(f"  - Transferred {invoice_count} invoices from Customer ID: {customer.id}")
                        total_invoices_merged += invoice_count
                    
                    # Update quotations to point to keeper
                    quotation_count = Quotation.objects.filter(quotation_customer=customer).count()
                    if quotation_count > 0:
                        Quotation.objects.filter(quotation_customer=customer).update(quotation_customer=keeper)
                        self.stdout.write(f"  - Transferred {quotation_count} quotations from Customer ID: {customer.id}")
                        total_quotations_merged += quotation_count
                    
                    self.stdout.write(f"  - Deleting Customer ID: {customer.id}")
                    customer.delete()
                    total_removed += 1
                
                # Recalculate keeper's book balance from all logs
                keeper_book = Book.objects.filter(customer=keeper, user=keeper.user).first()
                if keeper_book:
                    # Sum all book log changes
                    total_balance = BookLog.objects.filter(
                        parent_book=keeper_book,
                        is_active=True
                    ).aggregate(Sum('change'))['change__sum'] or 0
                    
                    # Get the most recent log
                    last_log = BookLog.objects.filter(
                        parent_book=keeper_book,
                        is_active=True
                    ).order_by('-id').first()
                    
                    # Update book
                    keeper_book.current_balance = total_balance
                    keeper_book.last_log = last_log
                    keeper_book.save()
                    
                    self.stdout.write(f"  ✓ Updated keeper's book balance: {total_balance}")

        self.stdout.write(
            self.style.SUCCESS(
                f'\n{"="*60}\n'
                f'Successfully removed {total_removed} duplicate customers from {total_groups} groups\n'
                f'Merged {total_books_merged} book records\n'
                f'Merged {total_book_logs_merged} book logs\n'
                f'Transferred {total_invoices_merged} invoices\n'
                f'Transferred {total_quotations_merged} quotations\n'
                f'All balances preserved and recalculated\n'
                f'{"="*60}'
            )
        )
