from django.contrib import admin
from django.urls import path, include

from web_app import views
from web_app.views import (
    index, category_detail, CustomLoginView, add_to_cart, cart_view, remove_from_cart, checkout_view,
    order_confirmation, register_view, vendor_dash, add_product, edit_product, delete_product, profile_view,
    profile_edit, invoice_view, download_report, print_report, vendor_edit_profile, category_list, inventory_view,
    settings_view, vendor_profile_view, reports_view, customer_list, product_list, vendor_products,
    sales_view, order_history_view, product_search, product_detail, mark_order_paid, customer_orders_view,
    vendor_orders_view, update_order_status, vendor_order_history, customer_order_history, create_checkout_session,
    success, cancel, customer_dashboard, stripe_webhook, activity_log_view, download_customer_order_history,
    print_customer_order_history, vendor_reports_view, vendor_orders)
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import render
from django.contrib.auth.views import LogoutView

urlpatterns = [
    path("admin/", admin.site.urls),

    # DRF routers for APIs
    path("api/", include("web_app.urls")),

    # Pages
    path("", index, name="index"),
    path("category/<int:category_id>/", category_detail, name="category_detail"),
    path("about/", lambda request: render(request, "about.html"), name="about"),
    path("contact/", lambda request: render(request, "contact.html"), name="contact"),

    # Auth
    path("accounts/login/", CustomLoginView.as_view(), name="login"),
    path("accounts/logout/", LogoutView.as_view(next_page="index"), name="logout"),
    path("accounts/register/", register_view, name="register"),
    path("accounts/profile/", profile_view, name="profile"),
    path("accounts/profile/edit/", profile_edit, name="profile_edit"),
    path("accounts/profile/invoice/<int:order_id>/", invoice_view, name="invoice"),
    path("profile/edit/", vendor_edit_profile, name="vendor_edit_profile"),

    # Cart handling
    path("cart/", cart_view, name="cart"),
    path("cart/add-auth/<int:product_id>/", add_to_cart, name="add_to_cart"),
    path("cart/remove/<int:product_id>/", remove_from_cart, name="cart_remove"),
    path("checkout/", checkout_view, name="checkout"),
    path("order/<int:order_id>/confirmation/", order_confirmation, name="order_confirmation"),

    # Stripe Payment
    path('create-checkout-session/', create_checkout_session, name='create_checkout_session'),
    path("success/<int:order_id>/", success, name="success"),
    path("cancel/<int:order_id>/", cancel, name="cancel"),
    path("stripe/webhook/", stripe_webhook, name="stripe_webhook"),

    # Vendor Dashboard
    path("vendor_dash/", vendor_dash, name="vendor_dash"),
    path("vendor/add/", add_product, name="add_product"),
    path("vendor/edit/<int:product_id>/", edit_product, name="edit_product"),
    path("vendor/delete/<int:product_id>/", delete_product, name="delete_product"),
    path("download_report/", download_report, name="download_report"),
    path("print_report/", print_report, name="print_report"),

    # Side panel
    path("categories/", category_list, name="category_list"),
    path("inventory/", inventory_view, name="inventory"),
    # Orders
    path("customer/orders", customer_orders_view, name="customer_orders"),
    path("vendor/orders", vendor_orders, name="vendor_orders"),
    path("vendor/orders_view", vendor_orders_view, name="vendor_orders_view"),

    path("customers/", customer_list, name="customer_list"),
    path("reports/", reports_view, name="reports"),
    path("vendor/profile/", vendor_profile_view, name="vendor_profile"),
    path("settings/", settings_view, name="settings"),
    path("products/", product_list, name="product_list"),
    path("vendor/products/", vendor_products, name="vendor_products"),
    path("vendor/sales/", sales_view, name="sales"),
    path("vendor/reports/", vendor_reports_view, name="vendor_reports"),
    path('vendor/reports/pdf/', views.vendor_reports_pdf_view, name='vendor_reports_pdf'),


    path("search/", product_search, name="product_search"),
    path("product/<int:product_id>/", product_detail, name="product_detail"),
    path("orders/<int:order_id>/mark_paid/", mark_order_paid, name="mark_order_paid"),
    path("orders/<int:order_id>/update/", update_order_status, name="update_order_status"),
    path("vendor/orders/history/", vendor_order_history, name="vendor_order_history"),
    path("order_history/", customer_order_history, name="customer_order_history"),
    path("customer_dashboard/", customer_dashboard, name="customer_dashboard"),
    path('vendor/activity_logs/', activity_log_view, name='vendor_activity_logs'),
    path('update-cart/', views.update_cart, name='update_cart'),

    path("orders/history/print/", print_customer_order_history, name="print_customer_order_history"),
    path("orders/history/download/", download_customer_order_history, name="download_customer_order_history"),

    # Admin Dashboard URLs
    path("admins/dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("admins/vendors/", views.admin_vendors, name="admin_vendors"),
    path("admins/customers/", views.admin_customers, name="admin_customers"),
    path("admins/analytics/", views.admin_analytics, name="admin_analytics"),
    path('admins/reports/', views.admin_reports, name='admin_reports'),
    path('admins/settings/', views.admin_settings, name='admin_settings'),
    path('admins/settings/backup/', views.admin_backup, name='admin_backup'),
    path('admins/settings/localization/', views.admin_update_localization, name='admin_update_localization'),
    path('admins/settings/account/', views.admin_update_account, name='admin_update_account'),



    # Admin Products
    path("admins/products/", views.admin_all_products, name="admin_all_products"),
    path("admins/products/<int:id>/view/", views.admin_product_detail, name="admin_product_detail"),
    path("admins/products/<int:id>/edit/", views.admin_product_edit, name="admin_product_edit"),
    path("admins/products/<int:id>/delete/", views.admin_product_delete, name="admin_product_delete"),


    path('vendors/<int:id>/edit/', views.admin_vendor_edit, name='admin_vendor_edit'),
    path('vendors/<int:id>/delete/', views.admin_vendor_delete, name='admin_vendor_delete'),
    path('vendors/<int:id>/', views.admin_vendor_detail, name='admin_vendor_detail'),

    # Customers management URLs
    path('admins/customers/<int:id>/', views.admin_customer_detail, name='admin_customer_detail'),
    path('admins/customers/<int:id>/edit/', views.admin_customer_edit, name='admin_customer_edit'),
    path('admins/customers/<int:id>/delete/', views.admin_customer_delete, name='admin_customer_delete'),

    # Admin Categories
    path('admins/categories/', views.admin_categories, name='admin_categories'),
    path('admins/category/add/', views.admin_category_add, name='admin_category_add'),
    path('admins/categories/<int:id>/edit/', views.admin_category_edit, name='admin_category_edit'),
    path('admins/categories/<int:id>/delete/', views.admin_category_delete, name='admin_category_delete'),

    # Admin Reports
    path('admins/reports/', views.admin_reports, name='admin_reports'),
    path('admins/reports/<str:report_id>/view/', views.admin_report_view, name='admin_report_view'),
    path('admins/reports/<str:report_id>/download/', views.admin_report_download, name='admin_report_download'),
    path('admins/reports/<str:report_id>/delete/', views.admin_report_delete, name='admin_report_delete'),

    # Admin Orders
    path("admins/orders/", views.admin_all_orders, name="admin_all_orders"),
    path('admins/orders/<int:id>/', views.admin_order_detail, name='admin_order_detail'),
    path('admins/orders/<int:id>/edit/', views.admin_order_edit, name='admin_order_edit'),
    path('admins/orders/<int:id>/delete/', views.admin_order_delete, name='admin_order_delete'),


    path('privacy-policy/', views.privacy_policy, name='privacy_policy'),
    path('terms-and-conditions/', views.terms_and_conditions, name='terms_and_conditions'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)