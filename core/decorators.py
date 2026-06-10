from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages

def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            if request.user.role not in roles and not request.user.is_superuser:
                messages.error(request, 'You do not have permission to access this page.')
                return redirect('dashboard')
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator

def log_activity(action, model_name=''):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            response = view_func(request, *args, **kwargs)
            if request.user.is_authenticated and request.method in ['POST']:
                from .models import ActivityLog
                ip = request.META.get('REMOTE_ADDR')
                ActivityLog.objects.create(user=request.user, action=action, model_name=model_name, ip_address=ip)
            return response
        return wrapper
    return decorator
