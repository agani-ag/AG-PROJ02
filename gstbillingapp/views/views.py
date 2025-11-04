# Django imports
from django.shortcuts import render


# ================= Static Pages ==============================
def landing_page(request):
    context = {}
    return render(request, 'landing_page.html', context)