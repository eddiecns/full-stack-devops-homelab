This is a virtual marketplace, where vendors and customers buy and sell bakery products conveniently. The app runs on Django, with external MySQL DB

Setup
1. Clone the repo git clone: git clone https://github.com/eddiecns/online_bakery_market.git 
2. and then run: cd online_bakery_market
3. Create a branch and switch to it: git checkout -b my_version
4. Create virtual environment: python -m venv .venv
5. Activate the venv source: .\.venv\Scripts\activate
6. Install dependencies: pip install -r requirements.txt
7. Copy the config file: cp .env.example .env
8. Edit .env and update your local settings: with MYSQl DB username, password and the Django secret key
9. Make migrations: python manage.py makemigrations
10. Run the migrations: python manage.py migrate
11. Create local admin user: python manage.py createsuperuser
12. Seed demo users and products: python manage.py seed_db or python manage.py seed_db --force
13. Start the app server: python manage.py runserver
14. Enter admin name, password  and email
15. Register for a demo account on https://dashboard.stripe.com/
16. Open Developers--> API keys --> copy and paste into the .env file the Publishable key and Secret key

Main app page will be accessed in browser on http://localhost:8000
Django/system dashboard is accessed on http://localhost:8000/admin
To expose the API endpoints documentation visit http://localhost:8000/swagger
You can also test the API using the Postman collection included in the repository.

Demo Users:
Django admin: u: admin p: admin
System Admin: u:eddie p: adminpass
Vendors: u: vendor1 p: vendorpass VendorID: ISK254
Vendor2: u:vendor2 p: vendorpass VendorID: LFE037
Customer1: u:customer1 p: customerpass

Stripe Online Transcations:

Card number: 4242 4242 4242 4242
Expiration date: any future date (e.g., 12/34)
CVC: any 3 digits (e.g., 123)

| Card Type        | Number              | Notes                           |
| ---------------- | ------------------- |---------------------------------|
| Visa             | 4242 4242 4242 4242 | Always succeeds                 |
| Visa             | 4000 0000 0000 9995 | Always fails(insufficient funds |
| Mastercard       | 5555 5555 5555 4444 | Always succeeds                 |
| American Express | 3782 822463 10005   | Always succeeds                 |

Vendor ID Management:
# Assign vendor IDs to all vendors who don't have one
python manage.py assign_vendor_ids

# Regenerate vendor IDs for ALL vendors (including those who already have one)
python manage.py assign_vendor_ids --all

# Assign vendor ID to a specific user
python manage.py assign_vendor_ids --username john_vendor

Features to add/fix in future

1. Split address fields in forms
2. Back to cart on checkout
3. Cancel pending orders
4. Edit pending orders
5. Forgot password
6. Email system
7. Freshdesk helpdesk intergration
8. SSO signup
9. Upload vendor business docs
10. Vendor Reviews
Reach out to me at eddie@ecns.co.za for any queries.

