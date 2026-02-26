from django.db import models

from .models import Category, Cart


def categories_context(request):
    return {
        "categories": Category.objects.all()
    }


def cart_item_count(request):
    count = 0
    if request.user.is_authenticated:
        from .models import Cart
        count = Cart.objects.filter(user=request.user).aggregate(
            total_qty=models.Sum('quantity')
        )['total_qty'] or 0
    return {'cart_item_count': count}

