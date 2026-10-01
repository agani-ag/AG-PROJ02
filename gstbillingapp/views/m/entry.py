"""/m/ — the one door the app link opens.

A person's link names the person, not a role, so this sends them to whatever they have: the
staff app when they hold a posting, their ledgers otherwise. Someone who is both an employee
here and a customer there lands on the staff app and can still open their ledger from it.
"""
from django.shortcuts import redirect

from ...mobile_auth import mobile_login_required


@mobile_login_required()
def entry(request):
    return redirect("m_employee_home" if request.mobile_actor["role"] == "employee"
                    else "m_customer_home")
