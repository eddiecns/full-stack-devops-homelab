from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db import models
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from .utils import generate_vendor_id
import uuid
from django.utils.text import slugify
import os
from PIL import Image
from io import BytesIO
from django.core.files.uploadedfile import InMemoryUploadedFile
import sys


# USERS / VENDORS
class CustomUser(AbstractUser):
    USER_TYPE_CHOICES = (
        ('customer', 'Customer'),
        ('vendor', 'Vendor'),
    )
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES)
    cell = models.CharField(max_length=15, blank=True, null=True)

    groups = models.ManyToManyField(
        Group,
        verbose_name='groups',
        blank=True,
        help_text='The groups this user belongs to.',
        related_name='customuser_set',
        related_query_name='customuser',
    )
    user_permissions = models.ManyToManyField(
        Permission,
        verbose_name='user permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        related_name='customuser_permissions_set',
        related_query_name='customuser_permissions',
    )


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    surname = models.CharField(max_length=100, blank=True)
    company_name = models.CharField(max_length=150, blank=True)
    vendor_id = models.CharField(max_length=50, unique=True, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True)
    mobile = models.CharField(max_length=20, blank=True)
    delivery_address = models.TextField(blank=True)
    payment_method = models.CharField(
        max_length=50,
        choices=[
            ("card", "Credit/Debit Card"),
            ("cash", "Cash on Delivery"),
            ("paypal", "PayPal")
        ],
        blank=True
    )

    def __str__(self):
        return f"{self.company_name} ({self.vendor_id})"


# Products

def category_image_upload_path(instance, filename):
    """
    Generate upload path for category images.
    Always saves as .jpg regardless of upload format.
    Format: products/{category_lowercase}/{CategoryName-without-s}.jpg
    """
    category_folder = slugify(instance.name).replace('-', '_')
    category_name = instance.name.rstrip('s') if instance.name.endswith('s') else instance.name
    new_filename = f'{category_name}.jpg'
    return f'products/{category_folder}/{new_filename}'


class Category(models.Model):
    name = models.CharField(max_length=50)
    image = models.ImageField(upload_to=category_image_upload_path, blank=True, null=True)

    def __str__(self):
        return self.name

    def get_category_folder_path(self):
        """Get absolute folder path for this category"""
        return os.path.join(settings.MEDIA_ROOT, "products", slugify(self.name).replace("-", "_"))

    def save(self, *args, **kwargs):
        """Convert uploaded image to JPG and save directly to category folder"""
        # Check if there's actually a file (new upload or existing)
        if self.image and self.image.name:
            try:
                # Try to open the image - will work for new uploads
                # Will fail for existing paths stored in DB
                img = Image.open(self.image)

                # If we got here, it's a new upload - process it
                # Convert to RGB if necessary
                if img.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')

                # Ensure folder exists
                folder_path = self.get_category_folder_path()
                os.makedirs(folder_path, exist_ok=True)

                # Save as JPG on disk
                category_name = self.name.rstrip('s') if self.name.endswith('s') else self.name
                filename = f"{category_name}.jpg"
                full_path = os.path.join(folder_path, filename)
                img.save(full_path, format='JPEG', quality=95)

                # Assign relative path to ImageField
                relative_path = os.path.join('products', slugify(self.name).replace('-', '_'), filename)
                self.image.name = relative_path

            except Exception as e:
                # If opening fails, it's an existing path - don't process
                pass

        super().save(*args, **kwargs)


def product_image_upload_path(instance, filename):
    """
    Generate upload path based on product category.
    Format: products/{category_slug}/{filename}
    """

    # Get the category name and convert to lowercase slug
    if instance.category:
        category_folder = slugify(instance.category.name).replace('-', '_')
    else:
        category_folder = 'uncategorized'

    # Generate unique filename to prevent overwrites
    name, ext = os.path.splitext(filename)
    unique_filename = f'{slugify(name)}_{uuid.uuid4().hex[:8]}{ext}'

    # Return the path: products/{category}/{unique_filename}
    return f'products/{category_folder}/{unique_filename}'


# Product model
class Product(models.Model):
    objects = None
    name = models.CharField(max_length=100)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock_quantity = models.IntegerField()
    availability = models.BooleanField(default=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    vendor = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="products")

    # Change this line to use the custom upload path
    image = models.ImageField(upload_to=product_image_upload_path)

    def __str__(self):
        return self.name


# Orders & Cart
class Cart(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)


class Order(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("cancelled", "Cancelled"),
    ]

    PAYMENT_CHOICES = [
        ("card", "Credit/Debit Card"),
        ("cash", "Cash on Delivery"),
        ("paypal", "PayPal"),
    ]

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="orders")
    products = models.ManyToManyField(Product, through='OrderItem')
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    delivery_address = models.TextField()
    payment_method = models.CharField(max_length=10, choices=PAYMENT_CHOICES, default="cash")
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    def vendor_items(self, vendor):
        return self.orderitem_set.filter(product__vendor=vendor)

    def vendor_subtotal(self, vendor):
        return sum(item.subtotal for item in self.vendor_items(vendor))

    @property
    def global_total(self):
        return sum(item.subtotal for item in self.orderitem_set.all())


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def subtotal(self):
        return self.quantity * self.price


class VendorSettings(models.Model):
    vendor = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    default_currency = models.CharField(max_length=3, default="R")
    low_stock_threshold = models.IntegerField(default=5)
    notify_new_order = models.BooleanField(default=True)
    notify_low_stock = models.BooleanField(default=True)
    default_report_period = models.CharField(max_length=10, default="week")

    def __str__(self):
        return f"Settings for {self.vendor.username}"


class ActivityLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    action = models.CharField(max_length=255)
    details = models.TextField(blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.timestamp} - {self.user} - {self.action}"


@receiver(post_save, sender=CustomUser)
def create_vendor_profile(sender, instance, created, **kwargs):
    if created and instance.user_type == 'vendor':
        profile, _ = Profile.objects.get_or_create(user=instance)
        if not profile.vendor_id:
            profile.vendor_id = generate_vendor_id()
            profile.save()