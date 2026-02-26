import random
import string

def log_activity(user, action, details=None, request=None, ip_address=None):
    """Create an activity log entry for a user."""
    if not user or not user.is_authenticated:
        return

    # Lazy import to avoid circular dependency
    from .models import ActivityLog

    # Get IP from request if possible
    if not ip_address and hasattr(request, "META"):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        ip_address = x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')

    ActivityLog.objects.create(
        user=user,
        action=action,
        details=details or "",
        ip_address=ip_address,
    )


def generate_vendor_id():
    """Generate a unique vendor ID in format: ABC123 (3 letters + 3 digits)."""
    from .models import Profile  # Lazy import inside the function

    while True:
        letters = ''.join(random.choices(string.ascii_uppercase, k=3))
        numbers = ''.join(random.choices(string.digits, k=3))
        vendor_id = f"{letters}{numbers}"

        # Check if this ID already exists
        if not Profile.objects.filter(vendor_id=vendor_id).exists():
            return vendor_id
