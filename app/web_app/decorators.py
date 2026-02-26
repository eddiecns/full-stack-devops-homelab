from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps


# Decorators for vendor and admin functions
def vendor_required(view_func):
    """Decorator to ensure only vendors can access certain views"""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if request.user.user_type != 'vendor':
            messages.error(request, 'Access denied. Vendors only.')
            return redirect('index')
        return view_func(request, *args, **kwargs)
    return wrapper


def admin_required(view_func):
    """Decorator to ensure only admins can access certain views"""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if request.user.user_type != 'admin':
            messages.error(request, 'Access denied. Admins only.')
            return redirect('index')
        return view_func(request, *args, **kwargs)
    return wrapper

