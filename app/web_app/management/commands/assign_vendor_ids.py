from django.core.management.base import BaseCommand
from web_app.models import CustomUser, Profile  # Change this line
from web_app.utils import generate_vendor_id  # Change this line


class Command(BaseCommand):
    help = 'Assign vendor IDs to existing vendor users who don\'t have one'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Regenerate vendor IDs for all vendors (even those who already have one)',
        )
        parser.add_argument(
            '--username',
            type=str,
            help='Assign vendor ID to a specific username',
        )

    def handle(self, *args, **options):
        if options['username']:
            # Assign to specific user
            try:
                user = CustomUser.objects.get(username=options['username'])
                if user.user_type != 'vendor':
                    self.stdout.write(
                        self.style.ERROR(f'User {user.username} is not a vendor')
                    )
                    return

                profile, created = Profile.objects.get_or_create(user=user)

                if profile.vendor_id and not options['all']:
                    self.stdout.write(
                        self.style.WARNING(
                            f'User {user.username} already has vendor ID: {profile.vendor_id}'
                        )
                    )
                    return

                old_id = profile.vendor_id
                profile.vendor_id = generate_vendor_id()
                profile.save()

                if old_id:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Updated vendor ID for {user.username}: {old_id} → {profile.vendor_id}'
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Assigned vendor ID to {user.username}: {profile.vendor_id}'
                        )
                    )

            except CustomUser.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'User {options["username"]} not found')
                )
            return

        # Process all vendors
        vendors = CustomUser.objects.filter(user_type='vendor')
        total_vendors = vendors.count()

        if total_vendors == 0:
            self.stdout.write(self.style.WARNING('No vendors found'))
            return

        self.stdout.write(f'Found {total_vendors} vendor(s)')

        assigned = 0
        skipped = 0
        updated = 0

        for vendor in vendors:
            profile, created = Profile.objects.get_or_create(user=vendor)

            if profile.vendor_id and not options['all']:
                skipped += 1
                self.stdout.write(
                    self.style.WARNING(
                        f'Skipped {vendor.username} (already has ID: {profile.vendor_id})'
                    )
                )
                continue

            old_id = profile.vendor_id
            profile.vendor_id = generate_vendor_id()
            profile.save()

            if old_id:
                updated += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Updated {vendor.username}: {old_id} → {profile.vendor_id}'
                    )
                )
            else:
                assigned += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Assigned {vendor.username}: {profile.vendor_id}'
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'\nSummary: {assigned} assigned, {updated} updated, {skipped} skipped'
            )
        )