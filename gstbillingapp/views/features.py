# Django imports
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from gstbilling import settings
import os


# ================= Features Pages ==============================
@login_required
def download_sqlite(request):
    # Define the path to the database file
    sqlite_path = os.path.join(settings.BASE_DIR, 'gstbillingdb.sqlite3')

    # Check if the file exists
    if os.path.exists(sqlite_path):
        # Open the file in binary mode
        with open(sqlite_path, 'rb') as f:
            # Create a response with the file content
            response = HttpResponse(f.read(), content_type='application/octet-stream')
            # Set the Content-Disposition header to indicate a file download
            response['Content-Disposition'] = 'attachment; filename="gstbillingdb.sqlite3"'
            return response
    else:
        return HttpResponse("Database file not found", status=404)
