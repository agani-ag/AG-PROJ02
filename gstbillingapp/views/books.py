# Django imports
from django.db.models import Sum
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

# Models
from ..models import Invoice
from ..models import Book
from ..models import BookLog

# Forms
from ..forms import BookLogForm


# ===================== Book views =============================
@login_required
def books(request):
    context = {}
    context['book_list'] = Book.objects.filter(user=request.user).exclude(customer_id__isnull=True)
    return render(request, 'books/books.html', context)


@login_required
def book_logs(request, book_id):
    context = {}
    book = get_object_or_404(Book, id=book_id, user=request.user)
    book_logs = BookLog.objects.filter(parent_book=book).order_by('-date')
    context['book'] = book
    context['book_logs'] = book_logs
    return render(request, 'books/book_logs.html', context)


@login_required
def book_logs_add(request, book_id):
    context = {}
    book = get_object_or_404(Book, id=book_id, user=request.user)
    book_logs = BookLog.objects.filter(parent_book=book)
    context['book'] = book
    context['book_logs'] = book_logs
    context['form'] = BookLogForm()

    if request.method == "POST":
        book_log_form = BookLogForm(request.POST)
        invoice_no = request.POST["invoice_no"]
        invoice = None
        if invoice_no:
            try:
                invoice_no = int(invoice_no)
                invoice = Invoice.objects.get(user=request.user, invoice_number=invoice_no)
            except:
                context['error_message'] = "Incorrect invoice number %s"%(invoice_no,)
                return render(request, 'books/book_logs_add.html', context)
                context['form'] = book_log_form
                return render(request, 'books/book_logs_add.html', context)


        book_log = book_log_form.save(commit=False)
        book_log.parent_book = book
        if invoice:
            book_log.associated_invoice = invoice
        book_log.save()

        book.current_balance = book.current_balance + book_log.change
        book.last_log = book_log
        book.save()
        return redirect('book_logs', book.id)

    return render(request, 'books/book_logs_add.html', context)

@login_required
def book_logs_del(request, booklog_id):
    bklg = get_object_or_404(BookLog, id=booklog_id)
    book = get_object_or_404(Book, id=bklg.parent_book.id, user=request.user)
    bklg.delete()
    new_total = BookLog.objects.filter(parent_book=book).aggregate(Sum('change'))['change__sum']
    new_last_log = BookLog.objects.filter(parent_book=book).last()
    if not new_total:
        new_total = 0
    book.current_balance = new_total
    book.last_log = new_last_log
    book.save()
    return redirect('book_logs', book.id)