from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from web_app.models import Category, Product, Cart, Order

User = get_user_model()


class BakeryAppTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Create users
        self.vendor = User.objects.create_user(
            username="vendor1",
            password="vendorpass",
            email="vendor1@example.com",
            user_type="vendor",
        )
        self.customer = User.objects.create_user(
            username="customer1",
            password="cust12345",
            email="customer1@example.com",
            user_type="customer",
        )

        # Category
        self.category = Category.objects.create(name="Cakes")

        # Product
        self.product = Product.objects.create(
            name="Chocolate Cake",
            description="Rich chocolate flavor",
            price=100.00,
            stock_quantity=10,
            category=self.category,
            vendor=self.vendor,
            availability=True,
            image=SimpleUploadedFile(
                "cake.jpg", b"fake-image-content", content_type="image/jpeg"
            ),
        )

    # TC01: Customer registration
    def test_customer_register(self):
        response = self.client.post(reverse('register'), {
            'username': 'newuser',
            'email': 'newuser@test.com',
            'password1': 'Testpass123!',
            'password2': 'Testpass123!',
            'user_type': 'customer',
        })
        self.assertIn(response.status_code, [200, 302])

    # TC02: Invalid login attempt
    def test_customer_login_invalid(self):
        response = self.client.post(reverse('login'), {
            'username': 'unknown',
            'password': 'wrongpass',
        })
        self.assertContains(response, "Please enter a correct username", html=False)

    # TC03: Customer views product list
    def test_customer_browse_products(self):
        self.client.login(username='customer1', password='cust12345')
        response = self.client.get(reverse('product_list'))
        self.assertIn(response.status_code, [200, 302])

    # TC04: Customer adds item to cart
    def test_add_to_cart(self):
        self.client.login(username='customer1', password='cust12345')
        response = self.client.post(
            reverse('add_to_cart', args=[self.product.id]),
            {'qty': 2}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Cart.objects.filter(user=self.customer, product=self.product).exists())

    # TC05: Successful checkout
    def test_checkout_valid_order(self):
        self.client.login(username='customer1', password='cust12345')
        # Add cart items first
        Cart.objects.create(user=self.customer, product=self.product, quantity=2)

        response = self.client.post(
            reverse('checkout'),
            {
                'delivery_address': '123 Test Street',
                'payment_method': 'cash'
            }
        )
        self.assertIn(response.status_code, [200, 302])
        self.assertTrue(Order.objects.filter(user=self.customer).exists())

    # TC06: Checkout with empty cart
    def test_checkout_empty_cart(self):
        self.client.login(username='customer1', password='cust12345')
        response = self.client.post(reverse('checkout'))
        self.assertIn(response.status_code, [200, 302, 400])

    # TC07: Vendor adds product
    def test_vendor_add_product(self):
        self.client.login(username='vendor1', password='vendorpass')

        # Create a minimal valid image using Pillow
        from PIL import Image
        from io import BytesIO

        # Create a 1x1 pixel image
        image_file = BytesIO()
        image = Image.new('RGB', (1, 1), color='red')
        image.save(image_file, 'JPEG')
        image_file.seek(0)

        uploaded_image = SimpleUploadedFile(
            "vanilla.jpg",
            image_file.read(),
            content_type="image/jpeg"
        )

        response = self.client.post(
            reverse('add_product'),
            data={
                'name': 'Vanilla Cake',
                'description': 'Soft vanilla cake',
                'price': '95.00',
                'stock_quantity': '5',
                'category': str(self.category.id),
                'availability': 'on',
                'image': uploaded_image
            },
            follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            Product.objects.filter(name='Vanilla Cake', vendor=self.vendor).exists(),
            msg="Vendor product creation failed — check required fields in add_product form."
        )

    # TC08: Vendor views dashboard
    def test_vendor_dashboard_access(self):
        self.client.login(username='vendor1', password='vendorpass')
        response = self.client.get(reverse('vendor_dash'))
        self.assertIn(response.status_code, [200, 302])

    # TC09: Vendor views sales page
    def test_vendor_sales_page(self):
        self.client.login(username='vendor1', password='vendorpass')
        response = self.client.get(reverse('sales'))
        self.assertIn(response.status_code, [200, 302])

    # TC10: Customer order history page
    def test_customer_order_history(self):
        self.client.login(username='customer1', password='cust12345')
        response = self.client.get(reverse('customer_order_history'))
        self.assertIn(response.status_code, [200, 302])

    # TC11: Test case to come later

    # TC12: Test case to come later


