import profile
import subprocess
from decimal import Decimal

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.staticfiles import finders
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404, render, redirect
from django.db import transaction
from django.contrib.auth.models import Group
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.contrib.auth.forms import UserCreationForm
from django import forms
from django.forms import ModelForm
from django.http import HttpResponseRedirect, JsonResponse, HttpResponse, FileResponse
from bakery_app.settings import MIN_ORDER_AMOUNT_ZAR
from .decorators import vendor_required, admin_required
from .models import (
    CustomUser, Profile, Category, Product, Cart, Order,
    OrderItem, VendorSettings, ActivityLog
)
from .serializers import (
    UserSerializer, ProfileSerializer, CategorySerializer,
    ProductSerializer, CartSerializer, OrderSerializer, OrderItemSerializer
)
from .forms import (
    ProfileForm, VendorProfileForm, VendorSettingsForm,
    VendorLoginForm, VendorForm, CustomerForm, CategoryForm, ProductForm, OrderForm, AdminVendorFullForm
)
from django import get_version as django_version
import sys
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import Sum, Prefetch, F, DecimalField, ExpressionWrapper, Max, Count, Avg
import stripe
from django.conf import settings
import logging
from .utils import log_activity
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import os
import uuid
from django.utils.text import slugify
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
import io
from datetime import datetime, timedelta, time
from collections import defaultdict
from .utils import generate_vendor_id
from django.db.models import Sum, Count, F, Q
from django.utils import timezone
from datetime import timedelta
import json


logger = logging.getLogger('portal')
stripe.api_key = settings.STRIPE_SECRET_KEY


# -----------------------------------------------------------------------------
# PUBLIC & NAVIGATION VIEWS
# -----------------------------------------------------------------------------
def index(request):
    """Homepage displaying all categories"""
    categories = Category.objects.all()
    return render(request, "index.html", {"categories": categories})


def category_detail(request, category_id):
    """Display products within a specific category"""
    category = get_object_or_404(Category, id=category_id)
    products = Product.objects.filter(category=category)

    cart_item_count = 0
    if request.user.is_authenticated:
        cart_item_count = Cart.objects.filter(user=request.user).aggregate(
            total=Sum('quantity')
        )['total'] or 0

    return render(request, "category_detail.html", {
        "category": category,
        "products": products,
        "cart_item_count": cart_item_count,
    })


@login_required
def category_list(request):
    """List all categories for logged-in users"""
    categories = Category.objects.all()
    return render(request, "category_list.html", {"categories": categories})


def product_detail(request, product_id):
    """Display detailed view of a single product"""
    product = get_object_or_404(Product, id=product_id)
    return render(request, "vendor/product_detail.html", {"product": product})


def product_search(request):
    """Search and filter products by name and category"""
    query = request.GET.get("q", "").strip()
    category_id = request.GET.get("category", "")

    products = Product.objects.all()
    if query:
        products = products.filter(name__icontains=query)
    if category_id:
        products = products.filter(category_id=category_id)

    context = {
        "products": products,
        "query": query,
        "category_id": category_id,
        "categories": Category.objects.all(),
    }
    return render(request, "search_results.html", context)


# -----------------------------------------------------------------------------
# AUTHENTICATION & PROFILE MANAGEMENT
# -----------------------------------------------------------------------------
class UserViewSet(viewsets.ModelViewSet):
    """API viewset for user management"""
    queryset = CustomUser.objects.all()
    serializer_class = UserSerializer

    @action(detail=False, methods=['post'])
    def register(self, request):
        """API endpoint for user registration"""
        username = request.data.get('username')
        password = request.data.get('password')
        email = request.data.get('email')
        cell = request.data.get('cell')
        user_type = request.data.get('user_type', '').lower()

        if user_type not in ['customer', 'vendor']:
            return Response({'error': 'Invalid user_type. Must be "customer" or "vendor".'},
                            status=status.HTTP_400_BAD_REQUEST)

        if CustomUser.objects.filter(username=username).exists():
            return Response({'error': 'Username already exists'}, status=status.HTTP_400_BAD_REQUEST)

        user = CustomUser.objects.create_user(
            username=username,
            password=password,
            email=email,
            cell=cell,
            user_type=user_type
        )

        profile = Profile.objects.create(user=user)

        vendor_id = None
        if user_type == 'vendor':
            vendor_id = generate_vendor_id()
            profile.vendor_id = vendor_id
            profile.save()

        group_name = 'Customers' if user_type == 'customer' else 'Vendors'
        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)

        # Log registration
        try:
            log_activity(
                user=user,
                action="Registered",
                details=f"New {user_type} registered with username: {username}. Vendor ID: {vendor_id if vendor_id else 'N/A'}"
            )
        except Exception:
            logger.exception("Failed to log registration activity for %s", username)

        response_data = UserSerializer(user).data
        if vendor_id:
            response_data['vendor_id'] = vendor_id
            response_data[
                'message'] = f"Registration successful! Your Vendor ID is: {vendor_id}. Please save it for login."

        return Response(response_data, status=status.HTTP_201_CREATED)


class ProfileViewSet(viewsets.ModelViewSet):
    """API viewset for profile management"""
    queryset = Profile.objects.all()
    serializer_class = ProfileSerializer


class RegisterForm(UserCreationForm):
    """Form for user registration"""
    email = forms.EmailField(required=True)
    cell = forms.CharField(
        max_length=15,
        required=False,  # Changed to not required
        label="Cell Number",
        initial=""  # Default empty value
    )
    user_type = forms.ChoiceField(
        choices=[("customer", "Customer"), ("vendor", "Vendor")],
        widget=forms.RadioSelect,
        required=True,
        initial="customer"  # Set default to customer
    )

    class Meta:
        model = CustomUser
        fields = ("username", "email", "cell", "user_type", "password1", "password2")


def register_view(request):
    """Handle user registration form"""
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.email = form.cleaned_data["email"]
            user.cell = form.cleaned_data.get("cell", "")  # Use get() with default empty string
            user.user_type = form.cleaned_data["user_type"]
            user.save()

            # Create or get profile
            profile, created = Profile.objects.get_or_create(user=user)

            # If user is a vendor, generate and assign vendor_id
            if user.user_type == "vendor":
                if not profile.vendor_id:  # Only generate if not already set
                    vendor_id = generate_vendor_id()
                    profile.vendor_id = vendor_id
                    profile.save()
                else:
                    vendor_id = profile.vendor_id

                # Display the vendor ID to the user
                messages.success(
                    request,
                    f"Account created successfully!"
                    f"Your Vendor ID is: {vendor_id}."
                )
            else:
                messages.success(request, "Account created successfully. You can now log in.")

            # Log registration event
            log_activity(
                user=user,
                action="Registered (Form)",
                details=f"User {user.username} registered via form. Vendor ID: {profile.vendor_id if user.user_type == 'vendor' else 'N/A'}",
                request=request
            )

            return redirect("login")
    else:
        form = RegisterForm()

    return render(request, "register.html", {"form": form})

class CustomLoginView(LoginView):
    """Custom login view with cart persistence"""
    template_name = "login.html"
    authentication_form = VendorLoginForm

    def form_valid(self, form):
        response = super().form_valid(form)

        pending_cart = self.request.session.pop("pending_cart", None)
        if pending_cart:
            product = Product.objects.get(id=pending_cart["product_id"])
            qty = int(pending_cart["qty"])

            cart_item, created = Cart.objects.get_or_create(
                user=self.request.user,
                product=product,
                defaults={"quantity": qty}
            )
            if not created:
                cart_item.quantity += qty
                cart_item.save()

        # Log successful login
        try:
            log_activity(
                user=self.request.user,
                action="Login",
                details="User logged in via CustomLoginView.",
                request=self.request
            )
        except Exception:
            logger.exception("Failed to log login for user %s", self.request.user.username)

        return response

    def get_success_url(self):
        user = self.request.user
        if user.user_type == "customer":
            return "/cart/"
        elif user.user_type == "vendor":
            return "/vendor_dash/"
        return "/"


@receiver(post_save, sender=CustomUser)
def create_profile_for_new_user(sender, instance, created, **kwargs):
    """Automatically create profile for new users"""
    if created:
        Profile.objects.get_or_create(user=instance)


@login_required
def profile_view(request):
    """View user profile (vendor view differs from customer)"""
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.user.user_type == "vendor":
        products = Product.objects.filter(vendor=request.user)
        sales = OrderItem.objects.filter(product__vendor=request.user).select_related("order", "product")
        for s in sales:
            s.line_total = s.price * s.quantity

        log_activity(
            user=request.user,
            action="Viewed Vendor Profile",
            details="Vendor accessed profile page.",
            request=request
        )

        return render(request, "vendor/vendor_profile.html", {
            "profile": profile,
            "products": products,
            "sales": sales,
        })

    else:
        log_activity(
            user=request.user,
            action="Viewed Customer Profile",
            details="Customer accessed profile page.",
            request=request
        )

        orders = Order.objects.filter(user=request.user).order_by("-created_at")

        return render(request, "profile.html", {
            "profile": profile,
            "orders": orders,
        })


@login_required
def profile_edit(request):
    """Edit profile (customer)"""
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form = ProfileForm(request.POST, instance=profile, user=request.user)
        if form.is_valid():
            form.save()
            log_activity(
                user=request.user,
                action="Edited Profile",
                details="Customer updated profile details",
                request=request
            )
            messages.success(request, "Profile updated successfully!")
            return redirect("profile")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = ProfileForm(instance=profile, user=request.user)

    return render(request, "profile_edit.html", {"form": form, "user": request.user})


@login_required
def vendor_edit_profile(request):
    """Edit profile (vendor)"""
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form = VendorProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            log_activity(
                user=request.user,
                action="Edited Profile",
                details="Vendor updated profile details",
                request=request
            )
            messages.success(request, "Profile updated successfully!")
            return redirect("profile")
    else:
        form = VendorProfileForm(
            instance=profile,
            initial={
                "first_name": request.user.first_name,
                "last_name": request.user.last_name,
                "email": request.user.email,
            }
        )

    # Make vendor_id readonly
    if 'vendor_id' in form.fields:
        form.fields['vendor_id'].widget.attrs['readonly'] = True

    return render(request, "vendor/vendor_edit_profile.html", {"form": form})


@login_required
def vendor_profile_view(request):
    """Vendor profile view - simple wrapper"""
    profile, _ = Profile.objects.get_or_create(user=request.user)
    log_activity(
        user=request.user,
        action="Viewed Vendor Profile",
        details="Vendor accessed profile page (vendor_profile_view).",
        request=request
    )
    return render(request, "vendor/vendor_profile.html", {"profile": profile})


# -----------------------------------------------------------------------------
# CUSTOMER (CART, ORDERS, REPORTS)
# -----------------------------------------------------------------------------
class CartViewSet(viewsets.ModelViewSet):
    """API viewset for cart management"""
    queryset = Cart.objects.all()
    serializer_class = CartSerializer

    @action(detail=False, methods=['post'])
    def add(self, request):
        """API endpoint to add item to cart"""
        user = request.user
        product_id = request.data.get('product_id')
        quantity = int(request.data.get('quantity', 1))

        product = get_object_or_404(Product, id=product_id)

        if product.stock_quantity < quantity:
            return Response({'error': 'Not enough stock'}, status=status.HTTP_400_BAD_REQUEST)

        cart_item, created = Cart.objects.get_or_create(user=user, product=product)
        if not created:
            cart_item.quantity += quantity
        else:
            cart_item.quantity = quantity
        cart_item.save()

        # Log cart addition
        log_activity(
            user=user,
            action="Added to Cart",
            details=f"Product {product.name} (ID {product.id}) x{quantity} added to cart.",
            request=request
        )

        return Response(CartSerializer(cart_item).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def remove(self, request):
        """API endpoint to remove item from cart"""
        user = request.user
        product_id = request.data.get('product_id')

        cart_item = Cart.objects.filter(user=user, product_id=product_id).first()
        if cart_item:
            cart_item.delete()
            log_activity(
                user=user,
                action="Removed from Cart",
                details=f"Removed product_id {product_id} from cart.",
                request=request
            )
            return Response({'success': 'Item removed from cart'}, status=status.HTTP_200_OK)
        return Response({'error': 'Item not found in cart'}, status=status.HTTP_404_NOT_FOUND)


def add_to_cart(request, product_id):
    """Add product to cart from product page"""
    if request.method == "POST":
        if request.user.is_authenticated and request.user.user_type in ['admin', 'vendor']:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'error': True,
                    'message': 'Admins and vendors cannot purchase products.'
                }, status=403)
            messages.error(request, 'Admins and vendors cannot purchase products.')
            return redirect('index')

        qty = int(request.POST.get("qty", 1))

        if request.user.is_authenticated:
            product = get_object_or_404(Product, id=product_id)
            cart_item, created = Cart.objects.get_or_create(
                user=request.user,
                product=product,
                defaults={"quantity": qty}
            )
            if not created:
                cart_item.quantity += qty
                cart_item.save()

            # Calculate total quantity (sum of all items)
            cart_items = Cart.objects.filter(user=request.user)
            cart_count = sum(item.quantity for item in cart_items)

            # Log add to cart
            log_activity(
                user=request.user,
                action="Added to Cart",
                details=f"Added {product.name} (ID {product.id}) qty {qty} to cart.",
                request=request
            )

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    "message": f'"{product.name}" added to cart!',
                    "quantity": cart_item.quantity,
                    "product_id": product.id,
                    "cart_count": cart_count
                })

            return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/"))

        else:
            request.session["pending_cart"] = {
                "product_id": product_id,
                "qty": qty
            }

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    "message": "Please log in to add items to your cart.",
                    "error": True
                }, status=401)

            return redirect("login")

    return redirect("index")

def update_cart(request):
    """Update cart quantities or remove items"""
    if request.method == "POST" and request.user.is_authenticated:
        if request.user.user_type in ['admin', 'vendor']:
            return JsonResponse({
                "error": "Admins and vendors cannot modify cart."
            }, status=403)

        product_id = request.POST.get("product_id")
        quantity = int(request.POST.get("quantity", 0))

        product = get_object_or_404(Product, id=product_id)
        cart_item = Cart.objects.filter(user=request.user, product=product).first()

        if cart_item:
            if quantity > 0:
                cart_item.quantity = quantity
                cart_item.save()
                log_activity(
                    user=request.user,
                    action="Updated Cart Item",
                    details=f"Set {product.name} (ID {product.id}) quantity to {quantity}.",
                    request=request
                )
            else:
                cart_item.delete()
                log_activity(
                    user=request.user,
                    action="Removed from Cart",
                    details=f"Removed {product.name} (ID {product.id}) from cart via update.",
                    request=request
                )

        cart_count = Cart.objects.filter(user=request.user).count()
        return JsonResponse({"cart_count": cart_count})

    return JsonResponse({"error": "Unauthorized"}, status=401)


@login_required
def cart_view(request):
    """Display and manage shopping cart"""
    user = request.user

    if user.user_type in ['admin', 'vendor']:
        messages.warning(request, 'Admins and vendors cannot access the shopping cart.')
        return redirect('index')

    profile, _ = Profile.objects.get_or_create(user=user)

    if request.method == "POST":
        # Handle AJAX request for cart count (total quantity)
        if request.POST.get('get_cart_count'):
            cart_items = Cart.objects.filter(user=user)
            cart_count = sum(item.quantity for item in cart_items)
            return JsonResponse({'cart_count': cart_count})

        product_id = request.POST.get("product_id")
        action = request.POST.get("action")
        qty_input = request.POST.get("quantity")

        if product_id and action:
            cart_item = get_object_or_404(Cart, user=user, product_id=product_id)
            product = cart_item.product

            if action == "increment":
                if cart_item.quantity < product.stock_quantity:
                    cart_item.quantity += 1
                    cart_item.save()
                    log_activity(user=user, action="Cart Increment", details=f"Incremented {product.name} in cart.",
                                 request=request)
                else:
                    messages.warning(request, f"Cannot add more. Only {product.stock_quantity} in stock.")
            elif action == "decrement":
                cart_item.quantity -= 1
                if cart_item.quantity <= 0:
                    cart_item.delete()
                    messages.info(request, f"{product.name} removed from cart.")
                    log_activity(user=user, action="Cart Remove", details=f"{product.name} removed from cart.",
                                 request=request)
                else:
                    cart_item.save()
                    log_activity(user=user, action="Cart Decrement", details=f"Decremented {product.name} in cart.",
                                 request=request)
            elif action == "update":
                try:
                    new_qty = int(qty_input)
                    if new_qty <= 0:
                        cart_item.delete()
                        messages.info(request, f"{product.name} removed from cart.")
                        log_activity(user=user, action="Cart Remove",
                                     details=f"{product.name} removed from cart (update).", request=request)
                    elif new_qty > product.stock_quantity:
                        messages.warning(request, f"Cannot set quantity higher than stock ({product.stock_quantity}).")
                    else:
                        cart_item.quantity = new_qty
                        cart_item.save()
                        messages.success(request, f"{product.name} quantity updated.")
                        log_activity(user=user, action="Cart Update",
                                     details=f"Updated {product.name} quantity to {new_qty}.", request=request)
                except ValueError:
                    messages.error(request, "Invalid quantity input.")

        return redirect("cart")

    cart_items = Cart.objects.filter(user=user)
    cart_data = []
    total = Decimal(0)
    for item in cart_items:
        subtotal = item.product.price * item.quantity
        total += subtotal
        cart_data.append({
            "product": item.product,
            "quantity": item.quantity,
            "price": item.product.price,
            "subtotal": subtotal,
        })

    return render(request, "cart.html", {
        "cart_items": cart_data,
        "total": total,
        "profile": profile,
    })

@require_POST
@login_required(login_url='/accounts/login/')
def remove_from_cart(request, product_id):
    """Remove specific item from cart"""
    if request.user.user_type in ['admin', 'vendor']:
        messages.error(request, 'Admins and vendors cannot modify cart.')
        return redirect('index')

    cart_item = Cart.objects.filter(user=request.user, product_id=product_id).first()
    if cart_item:
        cart_item.delete()
        log_activity(
            user=request.user,
            action="Removed from Cart",
            details=f"Removed product id {product_id} from cart.",
            request=request
        )
        messages.success(request, "Item removed from your cart.")
    else:
        messages.error(request, "Item not found in your cart.")
    return redirect("cart")


class OrderViewSet(viewsets.ModelViewSet):
    """API viewset for order management"""
    queryset = Order.objects.all()
    serializer_class = OrderSerializer

    @action(detail=False, methods=['post'])
    @transaction.atomic
    def checkout(self, request):
        """API endpoint for checkout process"""
        user = request.user
        delivery_address = request.data.get('delivery_address')

        cart_items = Cart.objects.filter(user=user)
        if not cart_items.exists():
            return Response({'error': 'Cart is empty'}, status=status.HTTP_400_BAD_REQUEST)

        total_price = 0
        order = Order.objects.create(user=user, total_price=0, delivery_address=delivery_address)

        for item in cart_items:
            product = item.product
            if product.stock_quantity < item.quantity:
                transaction.set_rollback(True)
                return Response({'error': f'Not enough stock for {product.name}'}, status=status.HTTP_400_BAD_REQUEST)

            product.stock_quantity -= item.quantity
            product.save()

            OrderItem.objects.create(order=order, product=product, quantity=item.quantity, price=product.price)
            total_price += product.price * item.quantity

        order.total_price = total_price
        order.save()
        cart_items.delete()

        log_activity(
            user=user,
            action="Order Placed (API)",
            details=f"Order ID {order.id} placed via API. Total R{order.total_price}",
            request=request
        )

        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


@login_required
def checkout_view(request):
    """Handle checkout process with payment options"""
    if request.method != "POST":
        return redirect('cart')

    user = request.user
    delivery_address = request.POST.get('delivery_address')
    payment_method = request.POST.get('payment_method')
    cart_items = Cart.objects.filter(user=user)

    if not cart_items.exists():
        return JsonResponse({'error': 'Cart is empty'}, status=400)

    total = sum(item.product.price * item.quantity for item in cart_items)

    order = Order.objects.create(
        user=user,
        delivery_address=delivery_address,
        total_price=total,
        payment_method=payment_method,
        status='pending'
    )

    for item in cart_items:
        OrderItem.objects.create(
            order=order,
            product=item.product,
            quantity=item.quantity,
            price=item.product.price
        )

    log_activity(
        user=user,
        action="Order Checkout",
        details=f"Order ID: {order.id}, Total: R{order.total_price}",
        request=request
    )

    cart_items.delete()

    if payment_method == 'cash':
        return JsonResponse({
            'success': True,
            'cod': True,
            'message': 'Your order has been placed and will be released once the vendor approves it.',
            'redirect_url': reverse('customer_orders')
        })

    elif payment_method == 'card':
        line_items = [
            {
                "price_data": {
                    "currency": "zar",
                    "product_data": {"name": item.product.name},
                    "unit_amount": int(item.price * 100),
                },
                "quantity": item.quantity,
            }
            for item in order.orderitem_set.all()
        ]

        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=line_items,
                mode='payment',
                success_url=request.build_absolute_uri(reverse('success', args=[order.id])),
                cancel_url=request.build_absolute_uri(reverse('cancel', args=[order.id])),
                metadata={'order_id': str(order.id)}
            )

            log_activity(
                user=user,
                action="Stripe Session Created",
                details=f"Stripe session created for Order {order.id}",
                request=request
            )

            return JsonResponse({'checkout_url': session.url})

        except Exception as e:
            logger.exception("Stripe checkout creation failed")
            return JsonResponse({'error': str(e)}, status=500)

    else:
        return JsonResponse({'error': 'PayPal payment is currently unavailable. Please use Card or Cash on Delivery.'}, status=400)


@login_required
def order_confirmation(request, order_id):
    """Display order confirmation page"""
    order = get_object_or_404(Order, id=order_id, user=request.user)
    order_items = OrderItem.objects.filter(order=order)

    log_activity(
        user=request.user,
        action="Viewed Order Confirmation",
        details=f"User viewed confirmation for Order {order.id}",
        request=request
    )

    return render(request, "order_confirmation.html", {
        "order": order,
        "order_items": order_items,
    })


@login_required
def customer_orders_view(request):
    """View pending customer orders"""
    orders = Order.objects.filter(
        user=request.user, status="pending"
    ).order_by("-created_at")

    log_activity(
        user=request.user,
        action="Viewed Pending Orders",
        details=f"Customer viewed pending orders (count {orders.count()})",
        request=request
    )

    return render(request, "customer_orders.html", {"orders": orders})


@login_required
def customer_orders(request):
    """View customer's pending orders (alias)"""
    orders = request.user.orders.filter(status="pending").order_by("-created_at")
    return render(request, "customer_orders.html", {"orders": orders})


@vendor_required
def order_history_view(request):
    """View order history for both customers and vendors"""
    if request.user.user_type == "customer":
        completed_orders = Order.objects.filter(user=request.user, status="paid").order_by("-created_at")
        cancelled_orders = Order.objects.filter(user=request.user, status="cancelled").order_by("-created_at")

        log_activity(
            user=request.user,
            action="Viewed Order History (Customer)",
            details=f"Customer viewed order history (completed {completed_orders.count()}).",
            request=request
        )

        return render(request, "order_history.html", {
            "completed_orders": completed_orders,
            "cancelled_orders": cancelled_orders,
        })

    elif request.user.user_type == "vendor":
        completed_orders = Order.objects.filter(
            orderitem__product__vendor=request.user,
            status="paid"
        ).distinct().order_by("-created_at")

        cancelled_orders = Order.objects.filter(
            orderitem__product__vendor=request.user,
            status="cancelled"
        ).distinct().order_by("-created_at")

        log_activity(
            user=request.user,
            action="Viewed Order History (Vendor)",
            details="Vendor viewed order history page.",
            request=request
        )

        return render(request, "vendor/vendor_order_history.html", {
            "completed_orders": completed_orders,
            "cancelled_orders": cancelled_orders,
        })

    else:
        messages.error(request, "You do not have permission to view this page.")
        return redirect("index")


@login_required
def customer_order_history(request):
    """View customer's order history"""
    completed_orders = request.user.orders.filter(status="paid").order_by("-created_at")
    cancelled_orders = request.user.orders.filter(status="cancelled").order_by("-created_at")

    log_activity(
        user=request.user,
        action="Downloaded/Viewed Order History (Customer)",
        details=f"Customer viewed order history (completed {completed_orders.count()}).",
        request=request
    )

    return render(request, "customer_order_history.html", {
        "completed_orders": completed_orders,
        "cancelled_orders": cancelled_orders,
    })


def customer_dashboard(request):
    """Customer dashboard showing all orders"""
    orders = request.user.orders.all() if request.user.is_authenticated else []
    return render(request, "customer_order_history.html", {"orders": orders})


@login_required
def download_customer_order_history(request):
    """Download PDF of customer order history"""
    completed_orders = Order.objects.filter(user=request.user, status='paid').order_by("-created_at")
    cancelled_orders = Order.objects.filter(user=request.user, status='cancelled').order_by("-created_at")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(name='CenterTitle', fontSize=18, leading=22, alignment=TA_CENTER, spaceAfter=10))
    styles.add(ParagraphStyle(name='CenterSubTitle', fontSize=12, leading=14, alignment=TA_CENTER, spaceAfter=20))
    styles.add(ParagraphStyle(name='HeadingLeft', fontSize=14, leading=16, alignment=TA_LEFT, spaceAfter=10))

    elements = []

    logo_path = finders.find('images/logo.png')
    if logo_path:
        try:
            logo = Image(logo_path, width=80, height=80)
            logo.hAlign = 'CENTER'
            elements.append(logo)
        except Exception as e:
            logger.exception("Error loading logo: %s", e)

    elements.append(Paragraph("<strong>Nyarie's Bakery</strong>", styles['CenterTitle']))
    elements.append(Paragraph("You Buy, We Serve", styles['CenterSubTitle']))
    elements.append(Paragraph("<strong>Order History Report</strong>", styles['CenterTitle']))
    elements.append(Spacer(1, 12))

    customer_data = [
        ["Name:", request.user.get_full_name()],
        ["Email:", request.user.email]
    ]
    if hasattr(request.user, 'profile'):
        if getattr(request.user.profile, 'phone', None):
            customer_data.append(["Phone:", request.user.profile.phone])
        if getattr(request.user.profile, 'address', None):
            customer_data.append(["Address:", request.user.profile.address])

    customer_table = Table(customer_data, colWidths=[100, 350])
    customer_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey)
    ]))
    elements.append(customer_table)
    elements.append(Spacer(1, 20))

    def create_order_table(orders, title, status_color):
        elements.append(Paragraph(title, styles['HeadingLeft']))
        if orders:
            data = [["Order #", "Date", "Total", "Delivery Address", "Status"]]
            for order in orders:
                data.append([
                    str(order.id),
                    order.created_at.strftime("%Y-%m-%d %H:%M"),
                    f"R{order.total_price:.2f}",
                    order.delivery_address,
                    order.status.title()
                ])
            table = Table(data, repeatRows=1, colWidths=[50, 80, 60, 180, 60])
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("TEXTCOLOR", (-1, 1), (-1, -1), status_color),
            ]))
            elements.append(table)
        else:
            elements.append(Paragraph(f"No {title.lower()}.", styles['Normal']))
        elements.append(Spacer(1, 12))

    create_order_table(completed_orders, "Completed Orders", colors.green)
    create_order_table(cancelled_orders, "Cancelled Orders", colors.red)

    timestamp = timezone.now().strftime("%Y-%m-%d %H:%M")
    elements.append(Spacer(1, 24))
    elements.append(Paragraph(f"Report generated on: {timestamp}", styles['Normal']))

    doc.build(elements)
    buffer.seek(0)

    log_activity(
        user=request.user,
        action="Downloaded Order History",
        details=f"Customer downloaded order history PDF. Completed: {completed_orders.count()}, Cancelled: {cancelled_orders.count()}",
        request=request
    )

    response = HttpResponse(buffer, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="order_history.pdf"'
    return response


@login_required
def print_customer_order_history(request):
    """Print-friendly customer order history"""
    customer = request.user
    completed_orders = Order.objects.filter(user=customer, status="paid").order_by("-created_at")
    cancelled_orders = Order.objects.filter(user=customer, status="cancelled").order_by("-created_at")

    log_activity(
        user=request.user,
        action="Printed Order History",
        details="Customer printed their order history.",
        request=request
    )

    return render(request, "print_order_history.html", {
        "completed_orders": completed_orders,
        "cancelled_orders": cancelled_orders,
    })


# -----------------------------------------------------------------------------
# VENDOR (PRODUCTS, ORDERS, REPORTS, SETTINGS)
# -----------------------------------------------------------------------------
class CategoryViewSet(viewsets.ModelViewSet):
    """API viewset for category management"""
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class ProductViewSet(viewsets.ModelViewSet):
    """API viewset for product management"""
    queryset = Product.objects.all()
    serializer_class = ProductSerializer


class ProductForm(ModelForm):
    """Form for adding/editing products"""
    class Meta:
        model = Product
        fields = ["name", "category", "price", "stock_quantity", "image", "description"]


@login_required
def vendor_dash(request):
    """Vendor dashboard showing their products"""
    if request.user.user_type not in ("vendor", "admin"):
        messages.error(request, "You don't have permission to view this page.")
        return redirect("index")

    products = Product.objects.filter(vendor=request.user)

    log_activity(
        user=request.user,
        action="Viewed Vendor Dashboard",
        details="Vendor accessed their dashboard.",
        request=request
    )

    return render(request, "vendor_dash.html", {"products": products})


@login_required
def add_product(request):
    """Add product (vendor)"""
    if request.user.user_type != "vendor":
        messages.error(request, "Only vendors can add products.")
        log_activity(request.user, "Unauthorized add_product attempt", "Attempted to add product without vendor role", request)
        return redirect("index")

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save(commit=False)
            product.vendor = request.user
            product.save()

            log_activity(
                user=request.user,
                action="Added Product",
                details=f"Product: {product.name} (ID {product.id})",
                request=request
            )

            messages.success(request, "Product added successfully.")
            return redirect("vendor_dash")
    else:
        form = ProductForm()

    return render(request, "product_form.html", {"form": form, "title": "Add Product"})


@login_required
def edit_product(request, product_id):
    """Edit existing product (vendors only)"""
    product = get_object_or_404(Product, id=product_id, vendor=request.user)

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            log_activity(
                user=request.user,
                action="Edited Product",
                details=f"Product: {product.name} (ID {product.id})",
                request=request
            )
            messages.success(request, "Product updated successfully.")
            return redirect("product_list")
    else:
        form = ProductForm(instance=product)

    return render(request, "product_form.html", {"form": form, "title": "Edit Product"})


@login_required
def delete_product(request, product_id):
    """Delete product (vendors only)"""
    product = get_object_or_404(Product, id=product_id, vendor=request.user)
    if request.method == "POST":
        log_activity(
            user=request.user,
            action="Deleted Product",
            details=f"Product: {product.name} (ID {product.id})",
            request=request
        )

        product.delete()
        messages.success(request, "Product deleted successfully.")
        return redirect("vendor_products")

    return render(request, "vendor/confirm_delete.html", {"product": product})


from django.db.models import Avg


@login_required
def product_list(request):
    """List vendor's products with pagination"""
    products_queryset = Product.objects.filter(vendor=request.user).order_by('name')

    # Pagination
    paginator = Paginator(products_queryset, 6)
    page_number = request.GET.get('page')
    products = paginator.get_page(page_number)

    # Stats
    total_products = products_queryset.count()
    avg_price = products_queryset.aggregate(avg_price=Avg('price'))['avg_price'] or 0

    log_activity(
        user=request.user,
        action="Viewed Product List",
        details=f"Viewed products page (page {page_number}).",
        request=request
    )

    return render(
        request,
        "vendor/product_list.html",
        {
            "products": products,
            "total_products": total_products,
            "avg_price": avg_price,
        }
    )


@login_required
def vendor_products(request):
    """Display vendor's product list"""
    if request.user.user_type != "vendor":
        messages.error(request, "You don't have permission to view this page.")
        return redirect("index")

    products = Product.objects.filter(vendor=request.user)

    log_activity(user=request.user, action="Viewed Vendor Products", details="Vendor viewed their product list.", request=request)

    return render(request, "vendor/vendor_products.html", {"products": products})


def product_image_upload_path(instance, filename):
    """Generate upload path based on product category"""
    if instance.category:
        category_folder = slugify(instance.category.name).replace('-', '_')
    else:
        category_folder = 'uncategorized'

    name, ext = os.path.splitext(filename)
    unique_filename = f'{slugify(name)}_{uuid.uuid4().hex[:8]}{ext}'
    return f'products/{category_folder}/{unique_filename}'


@login_required
def inventory_view(request):
    """View vendor inventory with stock tracking, low-stock prioritized and summary"""
    products_queryset = Product.objects.filter(vendor=request.user).order_by('stock_quantity', 'name')

    total_items_sold = 0
    for product in products_queryset:
        product.total_sold = OrderItem.objects.filter(
            product=product, order__status='paid'
        ).aggregate(total=Sum('quantity'))['total'] or 0
        total_items_sold += product.total_sold

    paginator = Paginator(products_queryset, 9)
    page_number = request.GET.get('page')
    products = paginator.get_page(page_number)

    low_stock_products = products_queryset.filter(stock_quantity__lt=5)
    total_low_stock = low_stock_products.count()
    total_products = products_queryset.count()

    log_activity(user=request.user, action="Viewed Inventory", details=f"Inventory viewed. Total products {total_products}. Low stock {total_low_stock}.", request=request)

    return render(request, "vendor/inventory.html", {
        "products": products,
        "low_stock_products": low_stock_products,
        "total_products": total_products,
        "total_items_sold": total_items_sold,
        "total_low_stock": total_low_stock,
    })


# VENDOR ORDER MANAGEMENT
@login_required
def get_vendor_orders(vendor, status_list=None):
    """
    Returns orders containing the vendor's products.
    Optionally filter by status.
    """
    qs = OrderItem.objects.filter(product__vendor=vendor)
    orders = Order.objects.filter(orderitem__product__vendor=vendor)
    if status_list:
        orders = orders.filter(status__in=status_list)

    vendor_items_qs = qs.select_related("product")
    orders = orders.prefetch_related(
        Prefetch("orderitem_set", queryset=vendor_items_qs, to_attr="vendor_items_list")
    ).distinct().order_by("-created_at")

    for order in orders:
        order.vendor_subtotal = sum(item.subtotal for item in order.vendor_items_list)

    return orders


@login_required
def vendor_orders(request):
    """View vendor's pending orders"""
    if request.user.user_type != "vendor":
        messages.error(request, "Access denied.")
        return redirect("index")

    # Get all orders containing vendor's products (not just pending)
    all_vendor_orders = Order.objects.filter(
        orderitem__product__vendor=request.user
    ).distinct()

    # Filter by status
    pending_orders = all_vendor_orders.filter(status="pending").order_by("-created_at")
    paid_orders = all_vendor_orders.filter(status="paid")
    cancelled_orders = all_vendor_orders.filter(status="cancelled")

    # Calculate statistics
    pending_count = pending_orders.count()
    paid_count = paid_orders.count()
    cancelled_count = cancelled_orders.count()

    # Prepare orders with vendor-specific data
    orders_with_vendor_data = []
    for order in pending_orders:
        order.vendor_items_list = order.vendor_items(request.user)
        order.vendor_subtotal = order.vendor_subtotal(request.user)
        orders_with_vendor_data.append(order)

    log_activity(
        user=request.user,
        action="Viewed Vendor Orders",
        details=f"Pending orders viewed ({pending_count}).",
        request=request
    )

    context = {
        "orders": orders_with_vendor_data,
        "pending_count": pending_count,
        "paid_count": paid_count,
        "cancelled_count": cancelled_count,
    }

    return render(request, "vendor/vendor_orders.html", context)


# This view is not being used for now, I will need to come back for it in time
@login_required
def vendor_orders_view(request):
    """View vendor's pending orders with enhanced details"""
    if request.user.user_type != "vendor":
        messages.error(request, "Access denied.")
        return redirect("index")

    orders = get_vendor_orders(request.user, status_list=["pending"])
    log_activity(user=request.user, action="Viewed Vendor Orders (detailed)", details="Vendor accessed detailed orders.", request=request)
    return render(request, "vendor/orders.html", {"orders": orders})


from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q


@login_required
def vendor_order_history(request):
    """View vendor's completed and cancelled orders"""
    if request.user.user_type != "vendor":
        messages.error(request, "Access denied.")
        return redirect("index")

    # Get paid and cancelled orders containing vendor's products
    all_vendor_orders = Order.objects.filter(
        orderitem__product__vendor=request.user
    ).distinct()

    orders = all_vendor_orders.filter(
        status__in=["paid", "cancelled"]
    ).order_by("-created_at")

    # Apply filters
    customer_filter = request.GET.get('customer', '').strip()
    order_number_filter = request.GET.get('order_number', '').strip()
    status_filter = request.GET.get('status', '')

    if customer_filter:
        orders = orders.filter(
            Q(user__username__icontains=customer_filter) |
            Q(user__first_name__icontains=customer_filter) |
            Q(user__last_name__icontains=customer_filter)
        )

    if order_number_filter:
        orders = orders.filter(id__icontains=order_number_filter)

    if status_filter and status_filter in ['paid', 'cancelled']:
        orders = orders.filter(status=status_filter)

    # Calculate statistics (based on all orders, not filtered)
    paid_count = all_vendor_orders.filter(status="paid").count()
    cancelled_count = all_vendor_orders.filter(status="cancelled").count()

    # Prepare orders with vendor-specific data
    orders_with_vendor_data = []
    for order in orders:
        order.vendor_items_list = order.vendor_items(request.user)
        order.vendor_subtotal = order.vendor_subtotal(request.user)
        orders_with_vendor_data.append(order)

    # Add pagination - 20 items per page
    paginator = Paginator(orders_with_vendor_data, 20)
    page = request.GET.get('page')

    try:
        paginated_orders = paginator.page(page)
    except PageNotAnInteger:
        paginated_orders = paginator.page(1)
    except EmptyPage:
        paginated_orders = paginator.page(paginator.num_pages)

    log_activity(
        user=request.user,
        action="Viewed Vendor Order History",
        details=f"Vendor viewed order history (page {paginated_orders.number} of {paginator.num_pages}).",
        request=request
    )

    context = {
        "orders": paginated_orders,
        "paid_count": paid_count,
        "cancelled_count": cancelled_count,
        "customer_filter": customer_filter,
        "order_number_filter": order_number_filter,
        "status_filter": status_filter,
    }

    return render(request, "vendor/vendor_order_history.html", context)


@login_required
def update_order_status(request, order_id):
    """
    Vendor updates status of their own orders.
    Only updates items that belong to the vendor.
    """
    if request.user.user_type != "vendor":
        messages.error(request, "Only vendors can update orders.")
        return redirect("vendor_orders")

    order = (
        Order.objects.filter(id=order_id, orderitem__product__vendor=request.user)
        .distinct()
        .first()
    )

    if not order:
        messages.error(request, "Order not found or not linked to your products.")
        return redirect("vendor_orders")

    if request.method == "POST":
        new_status = request.POST.get("status")
        if new_status in dict(Order.STATUS_CHOICES).keys():
            order.status = new_status
            order.save()

            for item in order.orderitem_set.filter(product__vendor=request.user):
                if new_status == "paid":
                    item.product.stock_quantity -= item.quantity
                    item.product.save()

            log_activity(
                user=request.user,
                action="Updated Order",
                details=f"Order #{order.id} marked as {new_status}",
                request=request
            )

            messages.success(request, f"Order #{order.id} updated to {new_status}.")
        else:
            messages.error(request, "Invalid status update.")

    return redirect("vendor_orders")


@login_required
def mark_order_paid(request, order_id):
    """Mark vendor order as paid and update inventory"""
    if request.user.user_type != "vendor":
        messages.error(request, "Only vendors can update orders.")
        return redirect("orders")

    order = get_object_or_404(Order, id=order_id)

    if not order.orderitem_set.filter(product__vendor=request.user).exists():
        messages.error(request, "You cannot update this order.")
        return redirect("orders")

    order.status = "paid"
    order.save()

    for item in order.orderitem_set.filter(product__vendor=request.user):
        product = item.product
        product.stock_quantity -= item.quantity
        product.save()

    log_activity(user=request.user, action="Marked Order Paid", details=f"Order #{order.id} marked as paid by vendor.", request=request)

    messages.success(request, f"Order #{order.id} marked as Paid.")
    return redirect("orders")


# VENDOR ANALYTICS & REPORTS

@login_required
def sales_view(request):
    """Display vendor sales dashboard with analytics"""
    if request.user.user_type != "vendor":
        messages.error(request, "You don't have permission to view this page.")
        return redirect("index")

    now = timezone.now()
    today = now.date()
    period = request.GET.get("period", "month")

    # Determine date range based on period
    if period == "day":
        start_date = today
        prev_start_date = today - timedelta(days=1)
        prev_end_date = today - timedelta(days=1)
    elif period == "week":
        start_date = today - timedelta(days=today.weekday())
        prev_start_date = start_date - timedelta(days=7)
        prev_end_date = start_date - timedelta(days=1)
    else:  # month
        start_date = today.replace(day=1)
        if start_date.month == 1:
            prev_start_date = start_date.replace(year=start_date.year - 1, month=12, day=1)
        else:
            prev_start_date = start_date.replace(month=start_date.month - 1, day=1)
        prev_end_date = start_date - timedelta(days=1)

    # Vendor products
    vendor_products = request.user.products.all()

    # All paid sales for vendor
    all_vendor_sales = OrderItem.objects.filter(
        product__vendor=request.user,
        order__status="paid"
    ).select_related("order", "product", "product__category")

    # Datetime ranges
    start_datetime = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
    end_datetime = timezone.make_aware(datetime.combine(today, datetime.max.time()))
    current_sales = all_vendor_sales.filter(order__created_at__range=(start_datetime, end_datetime))

    prev_start_datetime = timezone.make_aware(datetime.combine(prev_start_date, datetime.min.time()))
    prev_end_datetime = timezone.make_aware(datetime.combine(prev_end_date, datetime.max.time()))
    previous_sales = all_vendor_sales.filter(order__created_at__range=(prev_start_datetime, prev_end_datetime))

    # Metrics
    current_metrics = current_sales.aggregate(
        total_sales=Sum(F('quantity') * F('price'), output_field=DecimalField()),
        total_orders=Count('order', distinct=True)
    )
    previous_metrics = previous_sales.aggregate(
        total_sales=Sum(F('quantity') * F('price'), output_field=DecimalField()),
        total_orders=Count('order', distinct=True)
    )

    total_sales = float(current_metrics['total_sales'] or 0)
    prev_total_sales = float(previous_metrics['total_sales'] or 0)
    total_orders = current_metrics['total_orders'] or 0
    prev_total_orders = previous_metrics['total_orders'] or 0
    avg_sale = total_sales / total_orders if total_orders > 0 else 0

    # Growth calculations
    growth_rate = round(((total_sales - prev_total_sales) / prev_total_sales) * 100, 2) \
        if prev_total_sales > 0 else (100 if total_sales > 0 else 0)

    sales_change_percent = round(((total_sales - prev_total_sales) / prev_total_sales) * 100, 1) \
        if prev_total_sales > 0 else 0
    orders_change_percent = round(((total_orders - prev_total_orders) / prev_total_orders) * 100, 1) \
        if prev_total_orders > 0 else 0

    # Precompute daily start/end datetimes for optimization
    num_days = (today - start_date).days + 1
    day_ranges = [
        (
            timezone.make_aware(datetime.combine(start_date + timedelta(days=i), datetime.min.time())),
            timezone.make_aware(datetime.combine(start_date + timedelta(days=i), datetime.max.time()))
        )
        for i in range(num_days)
    ]

    # Daily sales data
    labels = [(start_date + timedelta(days=i)).strftime("%b %d") for i in range(num_days)]
    daily_data = [
        float(current_sales.filter(order__created_at__range=dr).aggregate(
            total=Sum(F('quantity') * F('price'), output_field=DecimalField())
        )['total'] or 0)
        for dr in day_ranges
    ]

    # Sales by Category
    category_sales = current_sales.values(
        category_name=F("product__category__name")
    ).annotate(
        total=Sum(F('quantity') * F('price'), output_field=DecimalField())
    ).order_by('-total')

    category_chart_labels = [c["category_name"] or "Uncategorized" for c in category_sales]
    category_chart_values = [float(c["total"] or 0) for c in category_sales]

    category_chart_data = [{
        "label": "Sales by Category",
        "data": category_chart_values,
        "borderColor": "rgba(139, 77, 35, 1)",
        "backgroundColor": "rgba(139, 77, 35, 0.1)",
        "tension": 0.4,
        "fill": True,
        "pointBackgroundColor": "rgba(139, 77, 35, 1)",
        "pointBorderColor": "#fff",
        "pointBorderWidth": 2,
        "pointRadius": 4
    }]

    # Sales per Product
    product_sales = current_sales.values(
        product_name=F("product__name")
    ).annotate(
        total=Sum(F('quantity') * F('price'), output_field=DecimalField())
    ).order_by('-total')[:10]

    product_chart_labels = [p["product_name"] for p in product_sales]
    product_chart_values = [float(p["total"] or 0) for p in product_sales]

    product_colors = [
        'rgba(139, 77, 35, 0.8)',
        'rgba(92, 51, 23, 0.8)',
        'rgba(101, 67, 33, 0.8)',
        'rgba(128, 85, 53, 0.8)',
        'rgba(160, 102, 60, 0.8)',
        'rgba(180, 120, 80, 0.8)',
        'rgba(200, 140, 100, 0.8)',
        'rgba(220, 160, 120, 0.8)',
        'rgba(230, 180, 140, 0.8)',
        'rgba(240, 200, 160, 0.8)',
    ]

    product_chart_data = [{
        "label": "Sales per Product",
        "data": product_chart_values,
        "backgroundColor": product_colors[:len(product_chart_values)],
        "borderColor": [c.replace('0.8', '1') for c in product_colors[:len(product_chart_values)]],
        "borderWidth": 2
    }]

    # Render context
    context = {
        "period": period,
        "total_sales": round(total_sales, 2),
        "total_orders": total_orders,
        "avg_sale": round(avg_sale, 2),
        "growth_rate": growth_rate,
        "sales_change_percent": abs(sales_change_percent),
        "orders_change_percent": abs(orders_change_percent),
        "category_chart_labels": json.dumps(category_chart_labels),
        "category_chart_data": json.dumps(category_chart_data),
        "product_chart_labels": json.dumps(product_chart_labels),
        "product_chart_data": json.dumps(product_chart_data),
    }

    log_activity(
        user=request.user,
        action="Viewed Sales Dashboard",
        details=f"Vendor viewed {period} sales analytics.",
        request=request
    )

    return render(request, "vendor/sales.html", context)


def filter_sales_by_period(user, period):
    """Helper function to filter sales by time period"""
    sales = OrderItem.objects.filter(product__vendor=user)
    now = timezone.now()

    if period == "day":
        sales = sales.filter(order__created_at__gte=now - timedelta(days=1))
    elif period == "week":
        sales = sales.filter(order__created_at__gte=now - timedelta(weeks=1))
    elif period == "month":
        sales = sales.filter(order__created_at__gte=now - timedelta(days=30))

    return sales


@login_required
def sales_dashboard(request):
    """Display vendor sales dashboard with analytics for day/week/month"""
    if request.user.user_type != "vendor":
        messages.error(request, "You don't have permission to view this page.")
        return redirect("index")

    now = timezone.now()
    today = now.date()
    period = request.GET.get("period", "month")

    if period == "day":
        start_date = today
    elif period == "week":
        start_date = today - timedelta(days=today.weekday())
    else:
        start_date = today.replace(day=1)

    sales = OrderItem.objects.filter(
        product__vendor=request.user,
        order__created_at__date__gte=start_date
    ).select_related("order", "product")

    total_sales = sales.aggregate(total=Sum("subtotal"))["total"] or 0
    total_orders = sales.count()
    avg_sale = sales.aggregate(avg=Sum("subtotal") / Count("id"))["avg"] or 0

    prev_start_date = start_date - timedelta(days=(today - start_date).days + 1)
    prev_sales = OrderItem.objects.filter(
        product__vendor=request.user,
        order__created_at__date__gte=prev_start_date,
        order__created_at__date__lt=start_date
    ).aggregate(total=Sum("subtotal"))["total"] or 1
    growth_rate = round((total_sales - prev_sales) / prev_sales * 100, 2)

    num_days = (today - start_date).days + 1
    labels = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(num_days)]
    daily_sales = sales.values("order__created_at__date").annotate(total=Sum("subtotal"))
    data = [next((x["total"] for x in daily_sales if x["order__created_at__date"] == start_date + timedelta(days=i)), 0) for i in range(num_days)]

    category_data = sales.values(category_name=F("product__category__name")).annotate(total=Sum("subtotal"))
    category_chart_labels = [c["category_name"] for c in category_data]
    category_chart_data = [{
        "label": "Sales by Category",
        "data": [c["total"] for c in category_data],
        "borderColor": "rgba(75, 192, 192, 1)",
        "backgroundColor": "rgba(75, 192, 192, 0.2)",
        "tension": 0.3,
        "fill": True
    }]

    product_data = sales.values(product_name=F("product__name")).annotate(total=Sum("subtotal"))
    product_chart_labels = [p["product_name"] for p in product_data]
    product_chart_data = [{
        "label": "Sales per Product",
        "data": [p["total"] for p in product_data],
        "backgroundColor": "rgba(54, 162, 235, 0.6)",
        "borderColor": "rgba(54, 162, 235, 1)",
        "borderWidth": 1
    }]

    context = {
        "period": period,
        "total_sales": total_sales,
        "total_orders": total_orders,
        "avg_sale": round(avg_sale, 2),
        "growth_rate": growth_rate,
        "chart_labels": json.dumps(labels),
        "chart_data": json.dumps(data),
        "category_chart_labels": json.dumps(category_chart_labels),
        "category_chart_data": json.dumps(category_chart_data),
        "product_chart_labels": json.dumps(product_chart_labels),
        "product_chart_data": json.dumps(product_chart_data),
    }

    log_activity(user=request.user, action="Viewed Sales Dashboard (period)", details=f"Vendor viewed {period} sales dashboard.", request=request)

    return render(request, "vendor/sales.html", context)


@login_required
def reports_view(request):
    if request.user.user_type != "vendor":
        messages.error(request, "Only vendors can view reports.")
        return redirect("index")

    period = request.GET.get("period", "all")
    sales = OrderItem.objects.filter(product__vendor=request.user, order__status="paid")
    now = timezone.now()

    # Filter by period
    if period == "day":
        start_date = now - timedelta(days=1)
        sales = sales.filter(order__created_at__gte=start_date)
    elif period == "week":
        start_date = now - timedelta(weeks=1)
        sales = sales.filter(order__created_at__gte=start_date)
    elif period == "month":
        start_date = now - timedelta(days=30)
        sales = sales.filter(order__created_at__gte=start_date)

    # Annotate subtotal using a different name
    sales = sales.annotate(calculated_subtotal=F("quantity") * F("price"))

    total_sales = sales.aggregate(
        total=Sum(F("price") * F("quantity"), output_field=DecimalField())
    )["total"] or 0

    # Pagination
    page = request.GET.get("page", 1)
    paginator = Paginator(sales.order_by('-order__created_at'), 10)

    try:
        sales_page = paginator.page(page)
    except PageNotAnInteger:
        sales_page = paginator.page(1)
    except EmptyPage:
        sales_page = paginator.page(paginator.num_pages)

    log_activity(
        user=request.user,
        action="Viewed Vendor Reports",
        details=f"Vendor viewed reports for period {period}.",
        request=request
    )

    return render(request, "vendor/reports.html", {
        "sales": sales_page,
        "total_sales": total_sales,
        "period": period,
        "paginator": paginator
    })

@login_required
def download_report(request):
    """Download PDF sales report (vendor)"""
    if request.user.user_type != "vendor":
        messages.error(request, "Only vendors can download reports.")
        return redirect("index")

    period = request.GET.get("period", "all")
    sales = OrderItem.objects.filter(product__vendor=request.user, order__status="paid")

    now = timezone.now()
    if period == "day":
        sales = sales.filter(order__created_at__gte=now - timedelta(days=1))
    elif period == "week":
        sales = sales.filter(order__created_at__gte=now - timedelta(weeks=1))
    elif period == "month":
        sales = sales.filter(order__created_at__gte=now - timedelta(days=30))

    total_sales = sum(item.price * item.quantity for item in sales)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(f"Sales Report ({period.title()})", styles["Title"]))
    elements.append(Spacer(1, 12))

    data = [["Order ID", "Product", "Qty", "Unit Price", "Total", "Date"]]
    for item in sales:
        data.append([
            str(item.order.id),
            item.product.name,
            str(item.quantity),
            f"R{item.price:.2f}",
            f"R{item.price * item.quantity:.2f}",
            item.order.created_at.strftime("%Y-%m-%d %H:%M"),
        ])

    data.append(["", "", "", "Total Sales", f"R{total_sales:.2f}", ""])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
        ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
    ]))

    elements.append(table)
    doc.build(elements)
    buffer.seek(0)

    log_activity(user=request.user, action="Downloaded Vendor Report", details=f"Downloaded {period} report. Total R{total_sales:.2f}.", request=request)

    response = HttpResponse(buffer, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="report_{period}.pdf"'
    return response


@login_required
def print_report(request):
    """Print-friendly vendor sales report"""
    if request.user.user_type != "vendor":
        messages.error(request, "Only vendors can print reports.")
        return redirect("index")

    period = request.GET.get("period", "all")
    sales_qs = OrderItem.objects.filter(product__vendor=request.user, order__status="paid")

    now = timezone.now()
    if period == "day":
        sales_qs = sales_qs.filter(order__created_at__gte=now - timedelta(days=1))
    elif period == "week":
        sales_qs = sales_qs.filter(order__created_at__gte=now - timedelta(weeks=1))
    elif period == "month":
        sales_qs = sales_qs.filter(order__created_at__gte=now - timedelta(days=30))

    sales = []
    total_sales = 0
    for item in sales_qs:
        item_total = item.price * item.quantity
        sales.append({
            "order_id": item.order.id,
            "product_name": item.product.name,
            "quantity": item.quantity,
            "unit_price": item.price,
            "total": item_total,
            "date": item.order.created_at,
        })
        total_sales += item_total

    log_activity(user=request.user, action="Printed Vendor Report", details=f"Printed {period} report. Total R{total_sales:.2f}.", request=request)

    return render(request, "vendor/print_report.html", {
        "sales": sales,
        "total_sales": total_sales,
        "period": period,
    })


@login_required
def settings_view(request):
    """Manage vendor settings and preferences"""
    if request.user.user_type != "vendor":
        messages.error(request, "Only vendors can access settings.")
        return redirect("index")

    settings_obj, _ = VendorSettings.objects.get_or_create(vendor=request.user)

    if request.method == "POST":
        form = VendorSettingsForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            settings_obj.default_currency = data["default_currency"]
            settings_obj.low_stock_threshold = data["low_stock_threshold"]
            settings_obj.notify_new_order = data["notify_new_order"]
            settings_obj.notify_low_stock = data["notify_low_stock"]
            settings_obj.default_report_period = data["default_report_period"]
            settings_obj.save()
            messages.success(request, "Settings saved successfully.")

            log_activity(user=request.user, action="Updated Vendor Settings", details="Vendor updated platform settings.", request=request)
            return redirect("settings")
    else:
        form = VendorSettingsForm(initial={
            "default_currency": settings_obj.default_currency,
            "low_stock_threshold": settings_obj.low_stock_threshold,
            "notify_new_order": settings_obj.notify_new_order,
            "notify_low_stock": settings_obj.notify_low_stock,
            "default_report_period": settings_obj.default_report_period,
        })

    return render(request, "vendor/settings.html", {"form": form})


@login_required
def customer_list(request):
    """List customers who have purchased from this vendor"""
    if request.user.user_type != "vendor":
        messages.error(request, "You don't have permission to view this page.")
        return redirect("index")

    customers = CustomUser.objects.filter(
        orders__orderitem__product__vendor=request.user,
        user_type="customer"
    ).distinct()

    customer_data = []
    overall_orders = 0
    overall_revenue = 0

    for customer in customers:
        # Get orders containing vendor's products
        orders = customer.orders.filter(
            orderitem__product__vendor=request.user
        ).distinct()

        total_orders = orders.count()

        # Calculate total spent by this customer on vendor's products
        total_spent = sum(
            order.vendor_subtotal(request.user)
            for order in orders
        )

        # Get last order date
        last_order = orders.order_by('-created_at').first()
        last_order_date = last_order.created_at if last_order else None

        # Add computed attributes to customer object
        customer.get_full_name = f"{customer.first_name} {customer.last_name}".strip() or customer.username
        customer.total_orders = total_orders
        customer.total_spent = total_spent
        customer.last_order = last_order_date

        customer_data.append(customer)

        # Accumulate overall stats
        overall_orders += total_orders
        overall_revenue += total_spent

    log_activity(
        user=request.user,
        action="Viewed Customers List",
        details=f"Vendor viewed {len(customer_data)} customers.",
        request=request
    )

    context = {
        "customers": customer_data,
        "total_orders": overall_orders,
        "total_revenue": overall_revenue,
    }

    return render(request, "vendor/customer_list.html", context)


# -----------------------------------------------------------------------------
# ADMIN (DASHBOARD, USERS, REPORTS, SETTINGS, AUDIT)
# -----------------------------------------------------------------------------
# admin_required decorator is expected to be present; keep definition if present earlier:
def admin_required(view_func):
    return user_passes_test(lambda u: u.is_authenticated and u.user_type == "admin")(view_func)


@admin_required
def admin_dashboard(request):
    """Admin dashboard displaying key platform statistics and health alerts."""
    total_products = Product.objects.count()
    total_vendors = CustomUser.objects.filter(user_type="vendor").count()
    total_customers = CustomUser.objects.filter(user_type="customer").count()

    total_orders = Order.objects.count()
    pending_orders = Order.objects.filter(status="pending").count()
    total_revenue = Order.objects.aggregate(total=Sum("total_price"))["total"] or 0

    low_stock_threshold = 5
    low_stock_products = Product.objects.filter(
        stock_quantity__lte=low_stock_threshold
    ).count()

    thirty_days_ago = timezone.now() - timedelta(days=30)
    inactive_vendors = CustomUser.objects.filter(
        user_type="vendor",
        last_login__lt=thirty_days_ago
    ).count()

    context = {
        "total_products": total_products,
        "total_vendors": total_vendors,
        "total_customers": total_customers,
        "total_orders": total_orders,
        "pending_orders": pending_orders,
        "total_revenue": total_revenue,
        "low_stock_products": low_stock_products,
        "inactive_vendors": inactive_vendors,
    }

    log_activity(
        user=request.user,
        action="Viewed Admin Dashboard",
        details="Admin accessed the main dashboard.",
        request=request
    )

    return render(request, "admins/admin_dashboard.html", context)


@admin_required
def admin_all_products(request):
    products = Product.objects.select_related("vendor", "category").all()

    # Get filter parameters
    search_query = request.GET.get('search', '')
    category_id = request.GET.get('category', '')
    vendor_id = request.GET.get('vendor', '')

    # Apply filters
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    if category_id:
        products = products.filter(category_id=category_id)

    if vendor_id:
        products = products.filter(vendor_id=vendor_id)

    # Get all categories and vendors for the filter dropdowns
    categories = Category.objects.all()
    vendors = CustomUser.objects.filter(user_type='vendor')

    # Pagination
    paginator = Paginator(products, 20)  # 20 products per page
    page_number = request.GET.get('page')
    products = paginator.get_page(page_number)

    log_activity(
        user=request.user,
        action="Viewed All Products",
        details="Admin viewed all vendor products.",
        request=request
    )

    context = {
        'products': products,
        'categories': categories,
        'vendors': vendors,
    }

    return render(request, "admins/admin_all_products.html", context)


@admin_required
def admin_product_detail(request, id):
    """
    View a single product's details (view-only).
    """
    product = Product.objects.select_related("vendor", "category").filter(id=id).first()
    if not product:
        messages.error(request, "Product not found.")
        return redirect("admin_all_products")

    # Log activity
    log_activity(
        user=request.user,
        action="Viewed Product",
        details=f"Admin viewed product '{product.name}' (ID: {product.id}).",
        request=request
    )

    return render(request, "admins/admin_product_detail.html", {"product": product})


@admin_required
def admin_product_edit(request, id):
    product = Product.objects.filter(id=id).first()
    if not product:
        messages.error(request, "Product not found.")
        return redirect("admin_all_products")

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, f"Product '{product.name}' updated successfully.")

            log_activity(
                user=request.user,
                action="Edited Product",
                details=f"Admin edited product '{product.name}' (ID: {product.id}).",
                request=request
            )

            return redirect("admin_all_products")
    else:
        form = ProductForm(instance=product)

    # Log viewing of edit page
    log_activity(
        user=request.user,
        action="Viewed Edit Product Page",
        details=f"Admin accessed edit page for product '{product.name}' (ID: {product.id}).",
        request=request
    )

    print(form.fields.keys())

    return render(request, "admins/admin_product_edit.html", {"form": form, "product": product})


@admin_required
def admin_product_delete(request, id):
    """
    Delete a product.
    """
    product = Product.objects.filter(id=id).first()
    if not product:
        messages.error(request, "Product not found.")
        return redirect("admin_all_products")

    if request.method == "POST":
        product_name = product.name
        product.delete()
        messages.success(request, f"Product '{product_name}' deleted successfully.")

        log_activity(
            user=request.user,
            action="Deleted Product",
            details=f"Admin deleted product '{product_name}' (ID: {id}).",
            request=request
        )
        return redirect("admin_all_products")

    # Optionally: confirm deletion page
    return render(request, "admins/admin_product_delete_confirm.html", {"product": product})


@admin_required
def admin_vendors(request):
    vendors = CustomUser.objects.filter(user_type="vendor")

    # Get filter parameters
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')

    # Apply search filter
    if search_query:
        vendors = vendors.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(profile__company_name__icontains=search_query) |
            Q(profile__vendor_id__icontains=search_query)
        )

    # Apply status filter
    if status_filter == 'active':
        vendors = vendors.filter(is_active=True)
    elif status_filter == 'inactive':
        vendors = vendors.filter(is_active=False)

    # Pagination
    paginator = Paginator(vendors, 20)  # 20 vendors per page
    page_number = request.GET.get('page')
    vendors = paginator.get_page(page_number)

    log_activity(
        user=request.user,
        action="Viewed Vendors List",
        details="Admin viewed the list of all vendors.",
        request=request
    )

    return render(request, "admins/admin_vendors.html", {"vendors": vendors})


@admin_required
def admin_vendor_detail(request, id):
    """
    Admin view for full vendor details (CustomUser + Profile)
    """
    vendor = get_object_or_404(CustomUser, id=id, user_type="vendor")
    profile = getattr(vendor, "profile", None)

    log_activity(
        user=request.user,
        action="Viewed Vendor Detail",
        details=f"Admin viewed vendor profile: {vendor.username} (ID: {vendor.id})",
        request=request
    )

    return render(request, "admins/admin_vendor_detail.html", {
        "vendor": vendor,
        "profile": profile,
    })


@admin_required
def admin_vendor_edit(request, id):
    vendor = get_object_or_404(CustomUser, id=id, user_type="vendor")
    profile, _ = Profile.objects.get_or_create(user=vendor)

    if request.method == "POST":
        form = AdminVendorFullForm(request.POST, instance=profile, user_instance=vendor)
        if form.is_valid():
            form.save()
            messages.success(request, "Vendor updated successfully.")
            log_activity(
                user=request.user,
                action="Edited Vendor",
                details=f"Admin updated vendor {vendor.username} (ID: {vendor.id}).",
                request=request
            )
            return redirect("admin_vendors")
    else:
        form = AdminVendorFullForm(instance=profile, user_instance=vendor)

    log_activity(
        user=request.user,
        action="Viewed Vendor Edit Page",
        details=f"Admin accessed vendor edit page for {vendor.username} (ID: {vendor.id}).",
        request=request
    )

    return render(request, "admins/admin_vendor_edit.html", {"form": form, "vendor": vendor})


@admin_required
def admin_vendor_delete(request, id):
    """
    Admin deletes a vendor account and their related data.
    """
    vendor = get_object_or_404(CustomUser, id=id, user_type="vendor")

    if request.method == "POST":
        username = vendor.username
        vendor.delete()
        messages.success(request, f"Vendor '{username}' deleted successfully.")

        # Activity Log Added
        log_activity(
            user=request.user,
            action="Deleted Vendor",
            details=f"Admin deleted vendor '{username}' (ID: {id}).",
            request=request
        )

        return redirect("admin_vendors")

    # Log viewing of delete confirmation page
    log_activity(
        user=request.user,
        action="Viewed Vendor Delete Page",
        details=f"Admin opened delete confirmation for vendor '{vendor.username}' (ID: {id}).",
        request=request
    )

    return render(request, "admins/admin_vendor_delete.html", {"vendor": vendor})

@admin_required
def admin_customer_detail(request, id):
    """
    Admin can view detailed customer profile, order history, and stats.
    """
    customer = get_object_or_404(CustomUser, id=id, user_type="customer")
    profile = getattr(customer, "profile", None)  # get related profile safely

    # Fetch customer's orders and total spend
    orders = Order.objects.filter(user=customer)
    total_orders = orders.count()
    total_spent = orders.aggregate(total=Sum("total_price"))["total"] or 0
    last_order = orders.aggregate(last=Max("created_at"))["last"]

    # Activity Log
    log_activity(
        user=request.user,
        action="Viewed Customer Detail",
        details=f"Admin viewed details for customer '{customer.username}' (ID: {customer.id}).",
        request=request
    )

    context = {
        "customer": customer,
        "profile": profile,
        "orders": orders,
        "total_orders": total_orders,
        "total_spent": total_spent,
        "last_order": last_order,
    }

    return render(request, "admins/admin_customer_detail.html", context)



@admin_required
def admin_customer_edit(request, id):
    """
    Admin can edit customer account details along with profile fields.
    """
    customer = get_object_or_404(CustomUser, id=id, user_type="customer")
    profile = getattr(customer, "profile", None)

    if request.method == "POST":
        user_form = CustomerForm(request.POST, instance=customer)
        profile_form = ProfileForm(request.POST, instance=profile)
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, "Customer updated successfully.")

            # Activity log
            log_activity(
                user=request.user,
                action="Edited Customer",
                details=f"Admin updated customer '{customer.username}' (ID: {customer.id}).",
                request=request
            )
            return redirect("admin_customers")
    else:
        user_form = CustomerForm(instance=customer)
        profile_form = ProfileForm(instance=profile)

    # Activity log for viewing
    log_activity(
        user=request.user,
        action="Viewed Customer Edit Page",
        details=f"Admin opened edit page for customer '{customer.username}' (ID: {customer.id}).",
        request=request
    )

    return render(
        request,
        "admins/admin_customer_edit.html",
        {
            "user_form": user_form,
            "profile_form": profile_form,
            "customer": customer
        }
    )


@admin_required
def admin_customer_delete(request, id):
    """
    Admin deletes a customer account and associated data.
    """
    customer = get_object_or_404(CustomUser, id=id, user_type="customer")

    if request.method == "POST":
        username = customer.username
        customer.delete()
        messages.success(request, f"Customer '{username}' deleted successfully.")

        # Activity Log Added
        log_activity(
            user=request.user,
            action="Deleted Customer",
            details=f"Admin deleted customer '{username}' (ID: {id}).",
            request=request
        )

        return redirect("admin_customers")

    # Log viewing of delete confirmation page
    log_activity(
        user=request.user,
        action="Viewed Customer Delete Page",
        details=f"Admin opened delete confirmation for customer '{customer.username}' (ID: {id}).",
        request=request
    )

    return render(request, "admins/admin_customer_delete.html", {"customer": customer})


@admin_required
def admin_customers(request):
    customers = CustomUser.objects.filter(user_type="customer")

    # Get filter parameters
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')

    # Apply search filter
    if search_query:
        customers = customers.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query)
        )

    # Apply status filter
    if status_filter == 'active':
        customers = customers.filter(is_active=True)
    elif status_filter == 'inactive':
        customers = customers.filter(is_active=False)

    # Pagination
    paginator = Paginator(customers, 20)  # 20 customers per page
    page_number = request.GET.get('page')
    customers = paginator.get_page(page_number)

    log_activity(
        user=request.user,
        action="Viewed Customers List",
        details="Admin viewed all customer profiles.",
        request=request
    )

    return render(request, "admins/admin_customers.html", {"customers": customers})


@admin_required
def admin_categories(request):
    categories = Category.objects.all()

    # Get search parameter
    search_query = request.GET.get('search', '')

    # Apply search filter
    if search_query:
        categories = categories.filter(name__icontains=search_query)

    # Order by name
    categories = categories.order_by('name')

    # Pagination
    paginator = Paginator(categories, 15)  # 20 categories per page
    page_number = request.GET.get('page')
    categories = paginator.get_page(page_number)

    log_activity(
        user=request.user,
        action="Viewed Categories",
        details="Admin viewed all product categories.",
        request=request
    )

    return render(request, "admins/admin_categories.html", {"categories": categories})


@admin_required
def admin_category_add(request):
    """
    Admin adds a new product category.
    """
    if request.method == "POST":
        form = CategoryForm(request.POST, request.FILES)
        if form.is_valid():
            category = form.save()
            messages.success(request, f"Category '{category.name}' added successfully.")

            # Activity Log Added
            log_activity(
                user=request.user,
                action="Added Category",
                details=f"Admin created a new category '{category.name}' (ID: {category.id}).",
                request=request
            )
            return redirect("admin_categories")
    else:
        form = CategoryForm()

    # Log viewing of category add page
    log_activity(
        user=request.user,
        action="Viewed Add Category Page",
        details="Admin accessed the category creation page.",
        request=request
    )

    return render(request, "admins/admin_category_add.html", {"form": form})


@admin_required
def admin_category_edit(request, id):
    category = get_object_or_404(Category, id=id)

    if request.method == "GET":
        log_activity(
            user=request.user,
            action="Viewed Edit Category Page",
            details=f"Admin accessed the edit page for category '{category.name}' (ID: {category.id}).",
            request=request
        )

    if request.method == "POST":
        print(f"DEBUG VIEW: request.FILES = {request.FILES}")
        print(f"DEBUG VIEW: request.POST = {request.POST}")

        form = CategoryForm(request.POST, request.FILES, instance=category)

        if form.is_valid():
            print(f"DEBUG VIEW: form.cleaned_data = {form.cleaned_data}")
            print(f"DEBUG VIEW: form.cleaned_data.get('image') = {form.cleaned_data.get('image')}")

            # Just save normally - let the form and model handle everything
            category = form.save()

            # ensure folder exists
            category_folder = os.path.join(
                settings.MEDIA_ROOT,
                "products",
                slugify(category.name).replace("-", "_")
            )
            os.makedirs(category_folder, exist_ok=True)

            log_activity(
                user=request.user,
                action="Updated Category",
                details=f"Admin updated category '{category.name}' (ID: {category.id}).",
                request=request
            )

            messages.success(request, "Category updated successfully")
            return redirect("admin_categories")

    else:
        form = CategoryForm(instance=category)

    return render(
        request,
        "admins/admin_category_form.html",
        {"form": form, "title": "Edit Category"}
    )


@admin_required
def admin_category_delete(request, id):
    category = get_object_or_404(Category, id=id)

    # Log category deletion
    log_activity(
        user=request.user,
        action="Deleted Category",
        details=f"Admin deleted category '{category.name}' (ID: {category.id}).",
        request=request
    )

    category.delete()
    messages.success(request, "Category deleted successfully")
    return redirect("admin_categories")


@admin_required
def admin_all_orders(request):
    """Admin view to see all orders with filtering and pagination."""

    orders = Order.objects.select_related("user").order_by("-created_at")

    # --- Filters ---
    search = request.GET.get("search", "")
    status = request.GET.get("status", "")
    date_str = request.GET.get("date", "")

    if search:
        orders = orders.filter(
            Q(user__username__icontains=search) |
            Q(orderitem__product__name__icontains=search)
        ).distinct()

    if status:
        orders = orders.filter(status=status)

    if date_str:
        try:
            filter_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            start_dt = timezone.make_aware(datetime.combine(filter_date, datetime.min.time()))
            end_dt = timezone.make_aware(datetime.combine(filter_date, datetime.max.time()))
            orders = orders.filter(created_at__gte=start_dt, created_at__lte=end_dt)
        except ValueError:
            pass

    # --- Pagination ---
    paginator = Paginator(orders, 15)  # 15 orders per page
    page_number = request.GET.get("page")
    orders_page = paginator.get_page(page_number)

    # --- Logging ---
    log_activity(
        user=request.user,
        action="Viewed All Orders (Admin)",
        details=f"Admin viewed all orders page with filters: search='{search}', status='{status}', date='{date_str}'.",
        request=request
    )

    return render(request, "admins/admin_all_orders.html", {"orders": orders_page})


@admin_required
def admin_order_edit(request, id):
    """Admin can edit an order."""
    order = get_object_or_404(Order, id=id)

    if request.method == "POST":
        form = OrderForm(request.POST, instance=order)
        if form.is_valid():
            form.save()
            messages.success(request, "Order updated successfully.")

            log_activity(
                user=request.user,
                action="Edited Order (Admin)",
                details=f"Admin updated order #{order.id}.",
                request=request
            )
            return redirect("admin_all_orders")
    else:
        form = OrderForm(instance=order)

    log_activity(
        user=request.user,
        action="Viewed Order Edit Page (Admin)",
        details=f"Admin opened edit page for order #{order.id}.",
        request=request
    )
    return render(request, "admins/admin_order_edit.html", {"form": form, "order": order})


@admin_required
def admin_order_delete(request, id):
    """Admin can delete an order (with confirmation)."""
    order = get_object_or_404(Order, id=id)

    if request.method == "POST":
        # User confirmed deletion
        order.delete()
        messages.success(request, f"Order #{id} deleted successfully.")

        log_activity(
            user=request.user,
            action="Deleted Order (Admin)",
            details=f"Admin deleted order #{id}.",
            request=request
        )
        return redirect("admin_all_orders")

    return render(request, "admins/admin_order_delete_confirm.html", {"order": order})


# Admin orders
@admin_required
def admin_order_detail(request, id):
    """Admin view to see order details (read-only)."""
    order = get_object_or_404(Order, id=id)
    log_activity(
        user=request.user,
        action="Viewed Order Details (Admin)",
        details=f"Admin viewed details for order #{id}.",
        request=request
    )
    return render(request, "admins/admin_order_detail.html", {"order": order})


@admin_required
def admin_analytics(request):
    # Totals
    total_products = Product.objects.count()
    total_orders = Order.objects.count()
    total_customers = CustomUser.objects.filter(user_type="customer").count()
    total_vendors = CustomUser.objects.filter(user_type="vendor").count()

    # Sales overview for past 30 days
    today = timezone.now().date()
    days = []
    orders_per_day = []

    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        start_dt = timezone.make_aware(datetime.combine(day, datetime.min.time()))
        end_dt = timezone.make_aware(datetime.combine(day, datetime.max.time()))
        days.append(day.strftime("%d %b"))
        count = Order.objects.filter(created_at__gte=start_dt, created_at__lte=end_dt).count()
        orders_per_day.append(count)

    # Vendor performance: total products sold per vendor
    vendor_items = OrderItem.objects.select_related("product__vendor")
    vendor_sales = defaultdict(int)
    for item in vendor_items:
        vendor_sales[item.product.vendor.username] += item.quantity

    vendor_labels = list(vendor_sales.keys())
    vendor_data = list(vendor_sales.values())

    context = {
        "total_products": total_products,
        "total_orders": total_orders,
        "total_customers": total_customers,
        "total_vendors": total_vendors,
        "sales_chart_labels": days,
        "sales_chart_data": orders_per_day,
        "vendor_chart_labels": vendor_labels,
        "vendor_chart_data": vendor_data,
    }

    log_activity(
        user=request.user,
        action="Viewed Admin Analytics",
        details="Admin viewed analytics dashboard.",
        request=request
    )

    return render(request, "admins/admin_analytics.html", context)


@admin_required
def admin_reports(request):
    """Admin reports dashboard — focusing on sales, vendors, and customers."""
    now = timezone.now()
    today = now.date()

    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')
    report_type = request.GET.get('report_type', '')

    all_orders = Order.objects.all().order_by('created_at')
    if all_orders.exists():
        first_order_date = all_orders.first().created_at.date()
        last_order_date = all_orders.last().created_at.date()
    else:
        first_order_date = today - timedelta(days=30)
        last_order_date = today

    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else first_order_date
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else last_order_date

    start_datetime = datetime.combine(start_date, time.min)
    end_datetime = datetime.combine(end_date, time.max)

    orders = Order.objects.filter(created_at__gte=start_datetime, created_at__lte=end_datetime)

    total_sales = orders.aggregate(total=Sum('total_price'))['total'] or 0
    total_vendors = CustomUser.objects.filter(user_type='vendor', is_active=True).count()
    total_customers = CustomUser.objects.filter(user_type='customer', is_active=True).count()

    reports = []

    if not report_type or report_type == 'sales':
        sales_by_date = defaultdict(lambda: {'total_amount': 0, 'order_count': 0})
        for order in orders:
            date_key = order.created_at.date()
            sales_by_date[date_key]['total_amount'] += order.total_price
            sales_by_date[date_key]['order_count'] += 1

        for order_date, data in sorted(sales_by_date.items(), reverse=True):
            reports.append({
                'id': f"SR-{order_date.strftime('%Y%m%d')}",
                'type': 'sales',
                'description': f"Daily Sales: R{float(data['total_amount']):.2f} from {data['order_count']} orders on {order_date.strftime('%d %b %Y')}",
                'created_at': datetime.combine(order_date, time.min),
                'generated_by': request.user,
            })

    if not report_type or report_type == 'vendors':
        vendor_items = OrderItem.objects.filter(order__created_at__gte=start_datetime, order__created_at__lte=end_datetime).select_related('product__vendor')
        vendor_sales = defaultdict(lambda: {'total_sales': 0, 'order_ids': set()})
        for item in vendor_items:
            vid = item.product.vendor.id
            vendor_sales[vid]['vendor_name'] = item.product.vendor.username
            vendor_sales[vid]['total_sales'] += item.price * item.quantity
            vendor_sales[vid]['order_ids'].add(item.order.id)

        top_vendors = sorted(vendor_sales.items(), key=lambda x: x[1]['total_sales'], reverse=True)[:10]
        for vid, data in top_vendors:
            reports.append({
                'id': f"VR-{vid}",
                'type': 'vendors',
                'description': f"Vendor '{data['vendor_name']}': R{float(data['total_sales']):.2f} from {len(data['order_ids'])} orders",
                'created_at': now,
                'generated_by': request.user,
            })

    if not report_type or report_type == 'customers':
        customer_sales = defaultdict(lambda: {'total_spent': 0, 'order_count': 0})
        for order in orders:
            uid = order.user.id
            customer_sales[uid]['customer_name'] = order.user.username
            customer_sales[uid]['total_spent'] += order.total_price
            customer_sales[uid]['order_count'] += 1

        top_customers = sorted(customer_sales.items(), key=lambda x: x[1]['total_spent'], reverse=True)[:10]
        for uid, data in top_customers:
            reports.append({
                'id': f"CR-{uid}",
                'type': 'customers',
                'description': f"Customer '{data['customer_name']}': R{float(data['total_spent']):.2f} from {data['order_count']} orders",
                'created_at': now,
                'generated_by': request.user,
            })

    context = {
        'reports': reports,
        'total_sales': float(total_sales),
        'total_vendors': total_vendors,
        'total_customers': total_customers,
        'start_date': start_date,
        'end_date': end_date,
    }

    log_activity(
        user=request.user,
        action="Generated Admin Report",
        details=f"Admin generated {report_type or 'all'} reports for {start_date} to {end_date}.",
        request=request
    )

    return render(request, "admins/admin_reports.html", context)


@admin_required
def admin_report_view(request, report_id):
    """Preview an admin report (sales, vendors, customers)."""
    # Determine report type
    if report_id.startswith("SR-"):
        report_type = "sales"
    elif report_id.startswith("VR-"):
        report_type = "vendors"
    elif report_id.startswith("CR-"):
        report_type = "customers"
    else:
        report_type = "unknown"

    # Date filters
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else timezone.now().date() - timezone.timedelta(days=30)
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else timezone.now().date()
    start_datetime = datetime.combine(start_date, time.min)
    end_datetime = datetime.combine(end_date, time.max)

    context = {"report_id": report_id, "report_type": report_type, "start_date": start_date, "end_date": end_date}

    # Reports
    if report_type == "sales":
        orders = Order.objects.filter(created_at__range=(start_datetime, end_datetime))
        context["orders"] = orders
        context["total_sales"] = orders.aggregate(total=Sum("total_price"))["total"] or 0
        template_name = "admins/reports/preview_sales.html"

    elif report_type == "vendors":
        vendor_items = OrderItem.objects.filter(order__created_at__range=(start_datetime, end_datetime)).select_related("product__vendor")
        vendor_sales = defaultdict(lambda: {"total_sales": 0, "orders": set()})
        for item in vendor_items:
            vid = item.product.vendor.id
            vendor_sales[vid]["vendor_name"] = item.product.vendor.username
            vendor_sales[vid]["total_sales"] += item.price * item.quantity
            vendor_sales[vid]["orders"].add(item.order.id)
        context["vendor_sales"] = vendor_sales.values()
        template_name = "admins/reports/preview_vendors.html"

    elif report_type == "customers":
        orders = Order.objects.filter(created_at__range=(start_datetime, end_datetime))
        customer_sales = defaultdict(lambda: {"total_spent": 0, "order_count": 0})
        for order in orders:
            uid = order.user.id
            customer_sales[uid]["customer_name"] = order.user.username
            customer_sales[uid]["total_spent"] += order.total_price
            customer_sales[uid]["order_count"] += 1
        context["customer_sales"] = customer_sales.values()
        template_name = "admins/reports/preview_customers.html"

    else:
        template_name = "admins/reports/preview_generic.html"

    # Logging for all report views
    log_activity(
        user=request.user,
        action="Viewed Admin Report Preview",
        details=f"Previewed {report_type} report {report_id} from {start_date} to {end_date}.",
        request=request
    )

    return render(request, template_name, context)



@admin_required
def admin_report_preview(request, report_id):
    """
    Return a small preview depending on the type encoded in report_id.
    (This function is optional; kept for parity with original file.)
    """
    # reconstruct logic to pick template and context (kept minimal)
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else timezone.now().date()
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else timezone.now().date()
    context = {"report_id": report_id, "start_date": start_date, "end_date": end_date}

    log_activity(user=request.user, action="Previewed Admin Report", details=f"Previewed report {report_id}.", request=request)

    return render(request, "admins/reports/preview_generic.html", context)


@admin_required
def admin_report_download(request, report_id):
    """Download admin report as PDF (sales, vendors, customers)."""
    now = timezone.now()

    # Identify report type
    if report_id.startswith("SR-"):
        report_type = "sales"
    elif report_id.startswith("VR-"):
        report_type = "vendors"
    elif report_id.startswith("CR-"):
        report_type = "customers"
    else:
        report_type = "unknown"

    # Prepare PDF buffer
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=30, rightMargin=30, topMargin=40, bottomMargin=30)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CenterTitle", fontSize=18, leading=22, alignment=1, spaceAfter=10))
    styles.add(ParagraphStyle(name="SubTitle", fontSize=12, leading=14, alignment=1, spaceAfter=20))
    styles.add(ParagraphStyle(name="Heading", fontSize=14, leading=16, spaceAfter=10))

    elements = []

    # Logo and title
    logo_path = finders.find("images/logo.png")
    if logo_path:
        logo = Image(logo_path, width=80, height=80)
        logo.hAlign = "CENTER"
        elements.append(logo)

    elements.append(Paragraph("<strong>Nyarie's Bakery</strong>", styles["CenterTitle"]))
    elements.append(Paragraph("Admin Analytics Report", styles["SubTitle"]))
    elements.append(Spacer(1, 12))

    # --- Generate Content per Report Type ---
    if report_type == "sales":
        orders = Order.objects.all().order_by("-created_at")
        data = [["Order ID", "Customer", "Date", "Total"]]
        for order in orders:
            data.append([order.id, order.user.username, order.created_at.strftime("%Y-%m-%d"), f"R{order.total_price:.2f}"])
        table = Table(data, repeatRows=1, colWidths=[60, 120, 100, 80])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(Paragraph("Sales Report", styles["Heading"]))
        elements.append(table)

    elif report_type == "vendors":
        elements.append(Paragraph("Vendor Sales Summary", styles["Heading"]))
        vendor_items = OrderItem.objects.select_related("product__vendor")
        data = [["Vendor", "Total Sales", "Orders Handled"]]
        vendor_totals = defaultdict(lambda: {"total": 0, "orders": set()})
        for item in vendor_items:
            v = item.product.vendor
            vendor_totals[v.username]["total"] += item.price * item.quantity
            vendor_totals[v.username]["orders"].add(item.order.id)
        for vname, vals in vendor_totals.items():
            data.append([vname, f"R{vals['total']:.2f}", len(vals["orders"])])
        table = Table(data, repeatRows=1, colWidths=[150, 100, 100])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(table)

    elif report_type == "customers":
        elements.append(Paragraph("Customer Spending Summary", styles["Heading"]))
        orders = Order.objects.all()
        customer_sales = defaultdict(lambda: {"total": 0, "orders": 0})
        for order in orders:
            customer_sales[order.user.username]["total"] += order.total_price
            customer_sales[order.user.username]["orders"] += 1
        data = [["Customer", "Orders", "Total Spent"]]
        for cname, vals in customer_sales.items():
            data.append([cname, vals["orders"], f"R{vals['total']:.2f}"])
        table = Table(data, repeatRows=1, colWidths=[150, 80, 100])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(table)

    # Timestamp footer
    elements.append(Spacer(1, 20))
    elements.append(Paragraph(f"Report generated on: {now.strftime('%Y-%m-%d %H:%M')}", styles["Normal"]))
    elements.append(Paragraph(f"Generated by: {request.user.username}", styles["Normal"]))

    # Build and send PDF
    doc.build(elements)
    buffer.seek(0)

    # Log the download action
    log_activity(
        user=request.user,
        action="Downloaded Admin Report",
        details=f"Downloaded {report_type} report {report_id}.",
        request=request
    )

    response = HttpResponse(buffer, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{report_id}.pdf"'
    return response


@admin_required
def admin_report_delete(request, report_id):
    """Delete a report (if using Report model)"""
    messages.success(request, "Report removed from view.")
    log_activity(user=request.user, action="Deleted Admin Report (virtual)", details=f"Admin {request.user.username} removed report {report_id}.", request=request)
    return redirect('admin_reports')



@admin_required
def admin_settings(request):
    context = {
        'django_version': django_version(),
        'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        'app_version': '1.0.0',
        'developer': 'eComputer Network Solutions',
        'support_contact': 'support@ecns.co.za',
    }

    log_activity(
        user=request.user,
        action="Viewed Admin Settings",
        details="Admin accessed platform settings.",
        request=request
    )
    return render(request, "admins/admin_settings.html", context)


@admin_required
def admin_report_preview_generic(request):
    """Generic preview stub for admin"""
    log_activity(user=request.user, action="Previewed Generic Admin Report", details="Previewed generic admin report.", request=request)
    return render(request, "admins/reports/preview_generic.html", {})


@admin_required
def activity_log_view(request):
    """View activity audit logs (admin-only)"""
    if request.user.user_type != "admin":
        messages.error(request, "Access denied.")
        return redirect("index")

    logs = ActivityLog.objects.select_related('user', 'user__profile').all()

    # Get filter parameters
    search_query = request.GET.get('search', '')
    user_type_filter = request.GET.get('user_type', '')
    action_filter = request.GET.get('action', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    # Apply search filter
    if search_query:
        logs = logs.filter(
            Q(action__icontains=search_query) |
            Q(details__icontains=search_query) |
            Q(user__username__icontains=search_query) |
            Q(user__email__icontains=search_query) |
            Q(ip_address__icontains=search_query)
        )

    # Apply user type filter
    if user_type_filter:
        logs = logs.filter(user__user_type=user_type_filter)

    # Apply action filter
    if action_filter:
        logs = logs.filter(action__icontains=action_filter)

    # Apply date range filters
    if date_from:
        logs = logs.filter(timestamp__date__gte=date_from)
    if date_to:
        logs = logs.filter(timestamp__date__lte=date_to)

    # Order by most recent
    logs = logs.order_by('-timestamp')

    # Get distinct actions for the filter dropdown
    distinct_actions = ActivityLog.objects.values_list('action', flat=True).distinct().order_by('action')

    # Pagination
    paginator = Paginator(logs, 15)  # 50 logs per page
    page_number = request.GET.get('page')
    logs = paginator.get_page(page_number)

    log_activity(
        user=request.user,
        action="Viewed Activity Logs",
        details=f"Admin viewed activity logs.",
        request=request
    )

    context = {
        'logs': logs,
        'distinct_actions': distinct_actions,
    }

    return render(request, "admins/activity_logs.html", context)


# -----------------------------------------------------------------------------
# PAYMENTS AND INTEGRATIONS
# -----------------------------------------------------------------------------
@csrf_exempt
def create_checkout_session(request):
    """Create Stripe checkout session for cart items"""
    if request.method == "POST":
        cart_items = Cart.objects.filter(user=request.user)
        if not cart_items.exists():
            return JsonResponse({'error': 'Cart is empty'}, status=400)

        order = Order.objects.create(
            user=request.user,
            total_price=0,
            status="pending",
        )

        line_items = []
        total_price = 0
        for item in cart_items:
            line_total = item.product.price * item.quantity
            OrderItem.objects.create(
                order=order,
                product=item.product,
                quantity=item.quantity,
                price=item.product.price,
            )
            total_price += line_total

            line_items.append({
                "price_data": {
                    "currency": "zar",
                    "product_data": {"name": item.product.name},
                    "unit_amount": int(item.product.price * 100),
                },
                "quantity": item.quantity,
            })

        order.total_price = total_price
        order.save()
        cart_items.delete()

        try:
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=line_items,
                mode="payment",
                success_url=request.build_absolute_uri(reverse("success", args=[order.id])),
                cancel_url=request.build_absolute_uri(reverse("cancel", args=[order.id])),
                metadata={"order_id": str(order.id)},
            )

            log_activity(user=request.user, action="Created Stripe Checkout", details=f"Stripe session for Order {order.id}", request=request)

            return JsonResponse({'checkout_url': session.url})

        except Exception as e:
            logger.exception("Stripe checkout error")
            return JsonResponse({'error': str(e)}, status=500)

    return redirect("cart")


@login_required
def success(request, order_id):
    """Handle successful payment completion"""
    order = Order.objects.get(id=order_id, user=request.user)
    order.status = "paid"
    order.save()

    log_activity(user=request.user, action="Payment Success", details=f"Order {order.id} marked paid (success view).", request=request)

    return render(request, "success.html", {"order": order})


@login_required
def cancel(request, order_id):
    """Handle payment cancellation"""
    order = Order.objects.get(id=order_id, user=request.user)
    order.status = "cancelled"
    order.save()

    order_items = order.orderitem_set.all()

    log_activity(user=request.user, action="Payment Cancelled", details=f"Order {order.id} payment cancelled.", request=request)

    return render(request, "cancel.html", {"order": order, "order_items": order_items})


@csrf_exempt
def stripe_webhook(request):
    """Handle Stripe webhook events"""
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    endpoint_secret = settings.STRIPE_WEBHOOK_SECRET

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponse(status=400)

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        order_id = session["metadata"]["order_id"]

        try:
            order = Order.objects.get(id=order_id)
            if order.status != "paid":
                order.status = "paid"
                order.save()

                for item in order.orderitem_set.all():
                    product = item.product
                    if product.stock_quantity >= item.quantity:
                        product.stock_quantity -= item.quantity
                        product.save()

                log_activity(user=order.user, action="Stripe Webhook - Marked Paid", details=f"Order {order.id} marked paid by webhook.", request=request)
        except Order.DoesNotExist:
            return HttpResponse(status=404)

    return HttpResponse(status=200)


@login_required
def stripe_success(request, order_id):
    """Handle Stripe payment success callback"""
    order = get_object_or_404(Order, id=order_id, user=request.user)

    if order.status != "paid":
        order.status = "paid"
        order.save()

        for item in order.orderitem_set.all():
            product = item.product
            if product.stock_quantity >= item.quantity:
                product.stock_quantity -= item.quantity
                product.save()

    log_activity(user=request.user, action="Stripe Success Callback", details=f"Order {order.id} marked paid (callback).", request=request)

    return render(request, "success.html", {"order": order})


def handle_paypal_payment(request, order):
    """
    PayPal payment handler - Currently not implemented.
    Provides friendly notification and alternative actions.
    """
    # Log the attempt
    log_activity(
        user=order.user,
        action="Attempted PayPal Payment",
        details=f"User tried PayPal for Order #{order.id} (currently inactive)",
        request=request
    )

    # Prepare frontend-friendly response
    response_data = {
        'status': 'failed',
        'message': "PayPal is currently unavailable. Please select an alternative payment method.",
        'alternatives': [
            {
                'method': 'Card',
                'url': reverse('checkout_card', kwargs={'order_id': order.id})
            },
            {
                'method': 'Cash on Delivery',
                'url': reverse('checkout_cod', kwargs={'order_id': order.id})
            }
        ]
    }

    return JsonResponse(response_data, status=400)


# -----------------------------------------------------------------------------
# INVOICES & DOCUMENTS
# -----------------------------------------------------------------------------
@login_required
def invoice_view(request, order_id):
    """Generate and display a well-formatted invoice PDF."""
    order = get_object_or_404(Order, id=order_id, user=request.user)

    log_activity(
        user=request.user,
        action="Viewed Invoice",
        details=f"Viewed invoice for Order {order.id}",
        request=request
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=40, bottomMargin=30)
    styles = getSampleStyleSheet()

    # Custom styles
    styles.add(ParagraphStyle(name='CenterTitle', fontSize=18, leading=22, alignment=TA_CENTER, spaceAfter=10))
    styles.add(ParagraphStyle(name='SubTitle', fontSize=12, leading=14, alignment=TA_CENTER, spaceAfter=15))
    styles.add(ParagraphStyle(name='NormalLeft', fontSize=11, leading=14, alignment=TA_LEFT, spaceAfter=6))
    styles.add(ParagraphStyle(name='HeadingLeft', fontSize=13, leading=16, alignment=TA_LEFT, spaceAfter=10))
    styles.add(ParagraphStyle(name='Bold', fontName='Helvetica-Bold', fontSize=11))

    elements = []

    # Add logo if available
    logo_path = finders.find('images/logo.png')
    if logo_path:
        logo = Image(logo_path, width=80, height=80)
        logo.hAlign = 'CENTER'
        elements.append(logo)

    # Header
    elements.append(Paragraph("<strong>Nyarie's Bakery</strong>", styles['CenterTitle']))
    elements.append(Paragraph("You Buy, We Serve", styles['SubTitle']))
    elements.append(Paragraph(f"<strong>Invoice for Order #{order.id}</strong>", styles['CenterTitle']))
    elements.append(Spacer(1, 10))

    # Customer + Order Info
    order_info = [
        ["Order ID:", str(order.id)],
        ["Date:", order.created_at.strftime("%Y-%m-%d")],
        ["Customer:", order.user.get_full_name() or order.user.username],
        ["Email:", order.user.email],
        ["Delivery Address:", order.delivery_address or "—"],
        ["Status:", order.status.capitalize() if order.status else "—"],
    ]

    order_table = Table(order_info, colWidths=[120, 360])
    order_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.lightgrey),
    ]))
    elements.append(order_table)
    elements.append(Spacer(1, 20))

    # Order Items
    elements.append(Paragraph("<strong>Order Items</strong>", styles['HeadingLeft']))

    item_data = [
        [Paragraph("<strong>Product</strong>", styles['Bold']),
         Paragraph("<strong>Quantity</strong>", styles['Bold']),
         Paragraph("<strong>Price (R)</strong>", styles['Bold']),
         Paragraph("<strong>Total (R)</strong>", styles['Bold'])]
    ]

    total = 0
    for item in order.orderitem_set.all():
        subtotal = item.price * item.quantity
        total += subtotal
        item_data.append([
            Paragraph(item.product.name, styles['NormalLeft']),
            str(item.quantity),
            f"{item.price:.2f}",
            f"{subtotal:.2f}"
        ])

    # Add total row (bold)
    item_data.append([
        "", "",
        Paragraph("<strong>Total:</strong>", styles['Bold']),
        Paragraph(f"<strong>R{total:.2f}</strong>", styles['Bold'])
    ])

    item_table = Table(item_data, colWidths=[200, 80, 80, 80])
    item_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(item_table)
    elements.append(Spacer(1, 30))

    # Footer
    elements.append(Paragraph("Thank you for your purchase!", styles['SubTitle']))

    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="invoice_{order.id}.pdf"'
    response.write(pdf)
    return response


@login_required
def vendor_reports_view(request):
    if request.user.user_type != "vendor":
        messages.error(request, "You are not authorized to view this page.")
        return redirect("index")

    # Vendor's products
    vendor_products = request.user.products.all()

    # Orders containing vendor's products
    vendor_order_items = OrderItem.objects.filter(product__vendor=request.user)
    vendor_orders = Order.objects.filter(orderitem__in=vendor_order_items).distinct().order_by('-created_at')

    # Total revenue
    total_revenue = sum(item.price * item.quantity for item in vendor_order_items)

    # Top-selling product
    top_product = (
        vendor_order_items
        .values('product__name')
        .annotate(total_sold=Sum('quantity'))
        .order_by('-total_sold')
        .first()
    )

    # Prepare orders with only this vendor's items and their subtotals
    orders_with_items = []
    for order in vendor_orders:
        items_qs = order.orderitem_set.filter(product__vendor=request.user)
        line_items = []
        subtotal = 0
        for item in items_qs:
            line_total = item.price * item.quantity
            subtotal += line_total
            line_items.append({
                "item": item,
                "line_total": line_total
            })
        if line_items:
            orders_with_items.append({
                "order": order,
                "items": line_items,
                "subtotal": subtotal,
            })

    context = {
        "vendor_products": vendor_products,
        "orders_with_items": orders_with_items,
        "total_revenue": total_revenue,
        "top_product": top_product,
    }

    return render(request, "vendor/vendor_reports.html", context)


@login_required
def vendor_reports_pdf_view(request):
    if request.user.user_type != "vendor":
        return HttpResponse("Unauthorized", status=403)

    # Fetch orders for this vendor
    orders_with_items = []
    vendor_products = request.user.products.all()
    for product in vendor_products:
        for order_item in product.orderitem_set.all():
            orders_with_items.append({
                "order": order_item.order,
                "items": [order_item],
                "subtotal": order_item.price * order_item.quantity
            })

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="vendor_reports.pdf"'

    doc = SimpleDocTemplate(response, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Nyarie's Bakery - Vendor Reports", styles['Title']))
    elements.append(Spacer(1, 12))

    for order_data in orders_with_items:
        elements.append(Paragraph(f"Order #{order_data['order'].id} - Status: {order_data['order'].status}", styles['Heading2']))
        table_data = [["Product", "Quantity", "Price (R)", "Subtotal (R)"]]
        for item in order_data['items']:
            table_data.append([
                item.product.name,
                item.quantity,
                f"{item.price:.2f}",
                f"{item.price * item.quantity:.2f}"
            ])
        table = Table(table_data, colWidths=[200, 80, 80, 80])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('ALIGN', (1,1), (-1,-1), 'RIGHT'),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 12))

    doc.build(elements)
    return response



@staff_member_required
def admin_backup(request):
    """Triggers manual database and media backup"""
    backup_dir = os.path.join(settings.BASE_DIR, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    db_file = os.path.join(backup_dir, f"db_backup_{timestamp}.sql")
    media_archive = os.path.join(backup_dir, f"media_backup_{timestamp}.tar.gz")

    # --- Database Backup ---
    try:
        subprocess.run(
            ["mysqldump", "-u", settings.DATABASES["default"]["USER"],
             f"-p{settings.DATABASES['default']['PASSWORD']}",
             settings.DATABASES["default"]["NAME"], ">", db_file],
            shell=True,
            check=True
        )
        # --- Media Backup ---
        subprocess.run(["tar", "-czf", media_archive, settings.MEDIA_ROOT], check=True)

        messages.success(request, f"Backup created successfully at {timestamp}.")
    except Exception as e:
        messages.error(request, f"Backup failed: {e}")

    return redirect("admin_settings")


@staff_member_required
def admin_update_localization(request):
    """Handle updates for language, currency, and timezone settings."""
    if request.method == "POST":
        language = request.POST.get("language")
        currency = request.POST.get("currency")
        timezone = request.POST.get("timezone")

        # Example: save them in a config model or settings table
        from .models import SiteSetting  # adjust to your model name
        site_settings, _ = SiteSetting.objects.get_or_create(id=1)
        site_settings.language = language
        site_settings.currency = currency
        site_settings.timezone = timezone
        site_settings.save()

        messages.success(request, "Localization settings updated successfully.")
    return redirect("admin_settings")


@staff_member_required
def admin_update_account(request):
    """Allow admin to update username, email, and password."""
    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        password = request.POST.get("password")
        password_confirm = request.POST.get("password_confirm")

        admin_user = request.user

        if password and password != password_confirm:
            messages.error(request, "Passwords do not match.")
            return redirect("admin_settings")

        # Update fields
        admin_user.username = username
        admin_user.email = email
        if password:
            admin_user.set_password(password)
        admin_user.save()

        messages.success(request, "Admin account updated successfully.")
        return redirect("admin_settings")


def privacy_policy(request):
    return render(request, 'privacy_policy.html')


def terms_and_conditions(request):
    return render(request, 'terms_and_conditions.html')
