from django.shortcuts import render
from django.views.decorators.cache import never_cache

@never_cache
def home(request):
    """
    Render the homepage with watershed delineation portal features.
    """
    # Check if user has just logged out, but only show the message on a fresh page load
    # If this is a request coming from sign-in button (via JS), we don't want to show logout message
    logged_out = False
    if 'logged_out_successfully' in request.session:
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            logged_out = request.session.pop('logged_out_successfully', False)
        else:
            # Clear the flag but don't show the message for AJAX requests
            request.session.pop('logged_out_successfully', False)
            logged_out = False
    
    context = {
        'title': 'Hydro WebPortal - Advanced Watershed Delineation',
        'year': '2024',
        'version': '1.0',
        'accuracy': '98.6',
        'method': 'Vector Method',
        'dataset': 'MERIT-Hydro',
        'logged_out': logged_out
    }
    return render(request, 'home.html', context)