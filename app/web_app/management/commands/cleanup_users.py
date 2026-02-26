from django.core.management.base import BaseCommand
from web_app.models import Product, CustomUser
from django.db import transaction
import random


class Command(BaseCommand):
    help = "Transfer half of vendor1's products to vendor2."

    def handle(self, *args, **kwargs):
        try:
            with transaction.atomic():
                # Get two vendors (adjust query if needed)
                vendors = list(CustomUser.objects.filter(user_type="vendor")[:2])
                if len(vendors) < 2:
                    self.stdout.write(self.style.ERROR("❌ Need at least 2 vendors."))
                    return

                vendor1, vendor2 = vendors

                # Get vendor1's products
                products = list(Product.objects.filter(vendor=vendor1))
                if not products:
                    self.stdout.write(self.style.WARNING(f"⚠️ No products found for {vendor1.username}"))
                    return

                # Shuffle and split
                random.shuffle(products)
                half = len(products) // 2
                products_to_transfer = products[:half]

                # Transfer half to vendor2
                for p in products_to_transfer:
                    p.vendor = vendor2
                    p.save()

                self.stdout.write(
                    self.style.SUCCESS(
                        f"✅ Transferred {len(products_to_transfer)} products "
                        f"from {vendor1.username} → {vendor2.username}."
                    )
                )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"⚠️ Error: {str(e)}"))
