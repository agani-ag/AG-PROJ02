from django.shortcuts import render
from django.http import Http404


class Custom404Middleware:
    """
    Middleware to show custom 404 page even when DEBUG = True
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        
        # Check if response is 404
        if response.status_code == 404:
            return render(request, '404.html', status=404)
        
        return response

    def process_exception(self, request, exception):
        """Handle Http404 exceptions"""
        if isinstance(exception, Http404):
            return render(request, '404.html', status=404)
        return None
