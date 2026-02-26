import random

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from web_app.models import Category, Product, Cart, Order, OrderItem

User = get_user_model()


class Command(BaseCommand):
    help = "Seeds the database with sample users, categories, products, carts, and orders."

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force seeding even if data exists',
        )

    def handle(self, *args, **options):
        force = options.get('force', False)

        # Check if data already exists
        if Product.objects.exists() and not force:
            self.stdout.write(self.style.SUCCESS("✅ Database already contains data. Skipping seed."))
            return

        if force:
            self.stdout.write(self.style.WARNING("🔄 Force flag detected. Clearing and re-seeding..."))
            Product.objects.all().delete()
            Category.objects.all().delete()
            Order.objects.all().delete()
            Cart.objects.all().delete()
            # Don't delete users when forcing, just update them

        self.stdout.write("🌱 Seeding database...")

        # === CREATE SUPERUSER ===
        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@crumbco.co.za",
                "user_type": "admin",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created or force:
            admin.set_password("admin")
            admin.save()
            self.stdout.write(self.style.SUCCESS("👤 Superuser 'admin' created (password: admin)"))

        # === USERS ===
        eddie, created = User.objects.get_or_create(
            username="eddie",
            defaults={
                "email": "eddie@crumbco.co.za",
                "user_type": "admin",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created or force:
            eddie.set_password("adminpass")
            eddie.save()

        vendor1, created = User.objects.get_or_create(
            username="vendor1",
            defaults={"email": "admin@bakeries.co.za", "user_type": "vendor"},
        )
        if created or force:
            vendor1.set_password("vendorpass")
            vendor1.save()

        vendor2, created = User.objects.get_or_create(
            username="vendor2",
            defaults={"email": "info@bakers.co.za", "user_type": "vendor"},
        )
        if created or force:
            vendor1.set_password("vendorpass")
            vendor1.save()

        customer1, created = User.objects.get_or_create(
            username="customer1",
            defaults={"email": "info@kasibakeries.co.za", "user_type": "customer"},
        )
        if created or force:
            customer1.set_password("customerpass")
            customer1.save()

        customer2, created = User.objects.get_or_create(
            username="customer2",
            defaults={"email": "orders@mcdonalds.co.za", "user_type": "customer"},
        )
        if created or force:
            customer1.set_password("customerpass")
            customer1.save()

        # === CATEGORIES ===
        categories = ["Cakes", "Breads", "Pastries", "Cookies", "Donuts", "Muffins", "Pizza", "Buns", "Pies",
                      "Cupcakes", "Brownies"]
        category_objs = {}
        for name in categories:
            obj, _ = Category.objects.get_or_create(name=name)
            category_objs[name] = obj

        # === PRODUCTS (5 per category with images) ===
        products_data = [
            # Cakes
            ("Chocolate Cake", "Rich chocolate cake", "Cakes", 15.99, 10, "products/cakes/cake1.jpg"),
            ("Vanilla Cake", "Classic vanilla cake", "Cakes", 12.99, 8, "products/cakes/cake2.jpg"),
            ("Red Velvet Cake", "Smooth red velvet cake", "Cakes", 16.50, 5, "products/cakes/cake3.jpg"),
            ("Lemon Cake", "Tangy lemon cake", "Cakes", 14.99, 7, "products/cakes/cake4.jpg"),
            ("Carrot Cake", "Moist carrot cake", "Cakes", 13.99, 6,
             "products/cakes/cake5.jpg"),

            # Breads
            ("Banana Bread", "Moist banana bread", "Breads", 16.99, 20, "products/breads/bread1.jpg"),
            ("Sourdough Bread", "Artisan sourdough", "Breads", 15.99, 15, "products/breads/bread2.jpg"),
            ("Whole Wheat Bread", "Healthy whole wheat bread", "Breads", 14.99, 18, "products/breads/bread3.jpg"),
            ("Rye Bread", "Classic rye bread", "Breads", 15.50, 12, "products/breads/bread4.jpg"),
            ("Baguette", "French baguette", "Breads", 13.99, 25, "products/breads/bread5.jpg"),

            # Pastries
            ("Croissant", "Buttery croissant", "Pastries", 13.99, 25, "products/pastries/pastry1.jpg"),
            ("Danish Pastry", "Fruit-filled danish", "Pastries", 14.50, 18, "products/pastries/pastry2.jpg"),
            ("Apple Turnover", "Crispy apple turnover", "Pastries", 13.75, 20, "products/pastries/pastry3.jpg"),
            ("Cheese Danish", "Soft cheese-filled pastry", "Pastries", 14.00, 15, "products/pastries/pastry4.jpg"),
            ("Éclair", "Chocolate-covered éclair", "Pastries", 14.25, 10, "products/pastries/pastry5.jpg"),

            # Cookies
            ("Chocolate Chip Cookie", "Loaded with chocolate chips", "Cookies", 11.99, 50,
             "products/cookies/cookie1.jpg"),
            ("Oatmeal Cookie", "Healthy oatmeal cookie", "Cookies", 11.50, 40, "products/cookies/cookie2.jpg"),
            ("Peanut Butter Cookie", "Rich peanut butter flavor", "Cookies", 11.75, 35, "products/cookies/cookie3.jpg"),
            ("Sugar Cookie", "Classic sweet cookie", "Cookies", 11.25, 45, "products/cookies/cookie4.jpg"),
            ("Chocolate Cookie", "Extra chocolatey goodness", "Cookies", 12.25, 30,
             "products/cookies/cookie5.jpg"),

            # Donuts
            ("Glazed Donut", "Sweet glazed donut", "Donuts", 11.25, 30, "products/donuts/donut1.jpg"),
            ("Chocolate Donut", "Chocolate-covered donut", "Donuts", 11.50, 25, "products/donuts/donut2.jpg"),
            ("Strawberry Donut", "Fruity strawberry donut", "Donuts", 11.40, 20, "products/donuts/donut3.jpg"),
            ("Boston Cream Donut", "Filled with cream", "Donuts", 11.60, 18, "products/donuts/donut4.jpg"),
            ("Cinnamon Donut", "Coated with cinnamon sugar", "Donuts", 11.35, 22, "products/donuts/donut5.jpg"),

            # Muffins
            ("Blueberry Muffin", "Soft muffin with fresh blueberries", "Muffins", 12.50, 20,
             "products/muffins/muffin1.jpg"),
            ("Chocolate Chip Muffin", "Muffin loaded with chocolate chips", "Muffins", 12.75, 18,
             "products/muffins/muffin2.jpg"),
            ("Banana Nut Muffin", "Banana muffin with crunchy nuts", "Muffins", 12.60, 15,
             "products/muffins/muffin3.jpg"),
            ("Lemon Poppyseed", "Tangy lemon muffin", "Muffins", 12.80, 12,
             "products/muffins/muffin4.jpg"),
            ("Cranberry Orange", "Sweet and tart cranberry", "Muffins", 12.70, 10,
             "products/muffins/muffin5.jpg"),

            # Pizza
            ("Margherita Pizza Slice", "Classic pizza with tomato, mozzarella, and basil", "Pizza", 23.50, 15,
             "products/pizza/pizza1.jpg"),
            ("Pepperoni Pizza Slice", "Cheesy pizza topped with spicy pepperoni", "Pizza", 23.75, 12,
             "products/pizza/pizza2.jpg"),
            ("BBQ Chicken Pizza", "Savory chicken with tangy BBQ sauce", "Pizza", 24.00, 10,
             "products/pizza/pizza3.jpg"),
            ("Veggie Delight Pizza", "Loaded with fresh vegetables and mozzarella", "Pizza", 23.60, 14,
             "products/pizza/pizza4.jpg"),
            ("Four Cheese Pizza Slice", "Blend of mozzarella, cheddar, parmesan, and gouda", "Pizza", 24.20, 8,
             "products/pizza/pizza5.jpg"),

            # Buns
            ("Sesame Bun", "Soft bun topped with sesame seeds", "Buns", 11.50, 25, "products/buns/bun1.jpg"),
            ("Garlic Knot", "Soft bread knot brushed with garlic butter", "Buns", 11.80, 20, "products/buns/bun2.jpg"),
            ("Cinnamon Bun", "Sweet bun with cinnamon swirl and icing glaze", "Buns", 12.20, 18,
             "products/buns/bun3.jpg"),
            ("Burger Bun", "Classic soft bun for burgers and sandwiches", "Buns", 11.40, 30, "products/buns/bun4.jpg"),
            ("Hot Dog Bun", "Fluffy bun perfect for hot dogs and sausages", "Buns", 11.30, 28, "products/buns/bun5.jpg"),

            # Pies
            ("Apple Pie Slice", "Classic apple pie with cinnamon", "Pies", 23.50, 15, "products/pies/pie1.jpg"),
            ("Cherry Pie Slice", "Sweet and tangy cherry filling", "Pies", 23.75, 12, "products/pies/pie2.jpg"),
            ("Pumpkin Pie Slice", "Spiced pumpkin custard pie", "Pies", 23.60, 10, "products/pies/pie3.jpg"),
            ("Pecan Pie Slice", "Sweet pecan filling with buttery crust", "Pies", 24.00, 8, "products/pies/pie4.jpg"),
            ("Blueberry Pie Slice", "Fresh blueberry filling in flaky crust", "Pies", 23.80, 14,
             "products/pies/pie5.jpg"),

            # Cupcakes
            ("Chocolate Cupcake", "Moist chocolate cupcake with frosting", "Cupcakes", 12.50, 20,
             "products/cupcakes/cupcake1.jpg"),
            ("Vanilla Cupcake", "Classic vanilla cupcake with buttercream", "Cupcakes", 12.40, 18,
             "products/cupcakes/cupcake2.jpg"),
            ("Red Velvet Cupcake", "Rich red velvet with cream cheese frosting", "Cupcakes", 12.70, 15,
             "products/cupcakes/cupcake3.jpg"),
            ("Strawberry Cupcake", "Fresh strawberry cupcake with pink icing", "Cupcakes", 12.60, 12,
             "products/cupcakes/cupcake4.jpg"),
            ("Cookies & Cream", "Topped with crushed Oreos", "Cupcakes", 12.80, 10,
             "products/cupcakes/cupcake5.jpg"),

            # Brownies
            ("Classic Brownie", "Rich chocolate fudge brownie", "Brownies", 12.00, 25, "products/brownies/brownie1.jpg"),
            ("Walnut Brownie", "Brownie topped with crunchy walnuts", "Brownies", 12.20, 20,
             "products/brownies/brownie2.jpg"),
            ("Cheesecake Brownie", "Swirled cheesecake and chocolate brownie", "Brownies", 12.50, 18,
             "products/brownies/brownie3.jpg"),
            ("Peanut Butter Brownie", "Brownie layered with peanut butter", "Brownies", 12.40, 15,
             "products/brownies/brownie4.jpg"),
            ("Salted Caramel", "Chocolate brownie with caramel drizzle", "Brownies", 12.60, 12,
             "products/brownies/brownie5.jpg"),
        ]

        product_objs = {}
        for name, desc, cat_name, price, stock, image in products_data:
            # Randomly assign to vendor1 or vendor2
            assigned_vendor = random.choice([vendor1, vendor2])

            prod, _ = Product.objects.get_or_create(
                name=name,
                defaults={
                    "vendor": assigned_vendor,
                    "category": category_objs[cat_name],
                    "description": desc,
                    "price": price,
                    "stock_quantity": stock,
                    "availability": True,
                    "image": image,
                },
            )
            product_objs[name] = prod

        # === CART ===
        Cart.objects.get_or_create(user=customer1, product=product_objs["Chocolate Cake"], defaults={"quantity": 2})
        Cart.objects.get_or_create(user=customer1, product=product_objs["Glazed Donut"], defaults={"quantity": 4})

        # === ORDERS ===
        order1, _ = Order.objects.get_or_create(
            user=customer1,
            defaults={
                "total_price": 45.00,
                "delivery_address": "23 Customer Lane, Parktown 7441",
                "created_at": timezone.now(),
            },
        )
        OrderItem.objects.get_or_create(order=order1, product=product_objs["Chocolate Cake"],
                                        defaults={"quantity": 2, "price": 15.99})
        OrderItem.objects.get_or_create(order=order1, product=product_objs["Glazed Donut"],
                                        defaults={"quantity": 4, "price": 11.25})

        self.stdout.write(self.style.SUCCESS("✅ Database seeded successfully!"))
        self.stdout.write(self.style.SUCCESS("🔐 Login credentials:"))
        self.stdout.write(self.style.SUCCESS("   Superuser: admin / admin"))
        self.stdout.write(self.style.SUCCESS("   Admin: eddie / adminpass"))
        self.stdout.write(self.style.SUCCESS("   Vendor: vendor1 and vendor2 / vendorpass"))
        self.stdout.write(self.style.SUCCESS("   Customer: customer1 / customerpass"))