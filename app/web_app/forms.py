from django import forms
from django.contrib.auth.forms import AuthenticationForm
from .models import Profile, CustomUser, Category, Product, Order


class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(required=True, label="First Name")
    last_name = forms.CharField(required=True, label="Last Name")
    email = forms.EmailField(required=True, label="Email")

    class Meta:
        model = Profile
        fields = ["phone", "mobile", "delivery_address", "payment_method"]
        labels = {"delivery_address": "Delivery Address"}

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["email"].initial = user.email
            self.user = user

        # Add Bootstrap classes to all fields
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            else:
                field.widget.attrs["class"] = "form-control"

    def save(self, commit=True):
        profile = super().save(commit=False)
        if hasattr(self, "user"):
            self.user.first_name = self.cleaned_data["first_name"]
            self.user.last_name = self.cleaned_data["last_name"]
            self.user.email = self.cleaned_data["email"]
            if commit:
                self.user.save()
        if commit:
            profile.save()
        return profile


class VendorProfileForm(forms.ModelForm):
    first_name = forms.CharField(required=False, label="First Name")
    last_name = forms.CharField(required=False, label="Last Name")
    email = forms.EmailField(required=False, label="Email")

    class Meta:
        model = Profile
        fields = ["company_name", "vendor_id", "phone", "mobile", "delivery_address"]
        labels = {"delivery_address": "Address"}

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        if user:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["email"].initial = user.email
            self.user = user

        # Add Bootstrap classes to all fields
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            else:
                field.widget.attrs["class"] = "form-control"

    def save(self, commit=True):
        profile = super().save(commit=False)
        user = profile.user
        user.first_name = self.cleaned_data.get("first_name", user.first_name)
        user.last_name = self.cleaned_data.get("last_name", user.last_name)
        user.email = self.cleaned_data.get("email", user.email)
        if commit:
            user.save()
            profile.save()
        return profile


class VendorSettingsForm(forms.Form):
    default_currency = forms.ChoiceField(
        choices=[("R", "Rand"), ("$", "ZimDollar"), ("K", "Kwacha")],
        initial="R",
        label="Default Currency"
    )

    low_stock_threshold = forms.IntegerField(
        initial=5, label="Low Stock Alert (Qty)"
    )
    notify_new_order = forms.BooleanField(
        required=False, initial=True, label="Email me for new orders"
    )
    notify_low_stock = forms.BooleanField(
        required=False, initial=True, label="Email me for low stock alerts"
    )
    default_report_period = forms.ChoiceField(
        choices=[("day", "Daily"), ("week", "Weekly"), ("month", "Monthly"), ("all", "All Time")],
        initial="week",
        label="Default Report Period"
    )


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = [
            'user',
            'delivery_address',
            'payment_method',
            'status'
        ]
        widgets = {
            'user': forms.Select(attrs={'class': 'form-select'}),
            'delivery_address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }


class VendorLoginForm(AuthenticationForm):
    vendor_id = forms.CharField(
        max_length=6,
        required=False,
        label="Vendor ID",
        widget=forms.TextInput(attrs={'placeholder': 'Enter Vendor ID (vendors only)'})
    )

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        vendor_id = cleaned_data.get('vendor_id')

        if username:
            try:
                user = CustomUser.objects.get(username=username)

                # If user is a vendor, vendor_id is required
                if user.user_type == 'vendor':
                    if not vendor_id:
                        raise forms.ValidationError("Vendor ID is required for vendor accounts.")

                    # Verify vendor_id matches
                    try:
                        profile = Profile.objects.get(user=user)
                        if profile.vendor_id != vendor_id:
                            raise forms.ValidationError("Invalid Vendor ID.")
                    except Profile.DoesNotExist:
                        raise forms.ValidationError("Profile not found.")

            except CustomUser.DoesNotExist:
                pass  # Will be caught by parent class validation

        return cleaned_data


class VendorForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ["username", "email", "is_active"]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class CustomerForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'first_name', 'last_name', 'is_active']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'image']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Category Name'
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
        }


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'name',
            'category',
            'vendor',
            'price',
            'stock_quantity',
            'availability',
            'description',
            'image',
        ]
        labels = {
            'name': 'Product Name',
            'category': 'Category',
            'vendor': 'Vendor',
            'price': 'Price',
            'stock_quantity': 'Stock Quantity',
            'availability': 'Availability',
            'description': 'Product Description',
            'image': 'Product Image',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Limit vendors to only users with user_type='vendor'
        self.fields['vendor'].queryset = CustomUser.objects.filter(user_type='vendor')

        # Add Bootstrap classes
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs['class'] = 'form-select'
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-check-input'
            else:
                field.widget.attrs['class'] = 'form-control'

        # Make checkbox label appear correctly
        self.fields['availability'].label = "Active"


class AdminVendorFullForm(forms.ModelForm):
    # Include related user fields
    username = forms.CharField(label="Username", required=True)
    email = forms.EmailField(label="Email", required=True)
    first_name = forms.CharField(label="First Name", required=False)
    last_name = forms.CharField(label="Last Name", required=False)
    is_active = forms.BooleanField(label="Active", required=False)

    class Meta:
        model = Profile
        fields = [
            "company_name",
            "surname",
            "vendor_id",
            "phone",
            "mobile",
            "delivery_address",
        ]
        labels = {"delivery_address": "Delivery Address"}

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user_instance", None)
        super().__init__(*args, **kwargs)

        if user:
            self.user_instance = user
            self.fields["username"].initial = user.username
            self.fields["email"].initial = user.email
            self.fields["first_name"].initial = user.first_name
            self.fields["is_active"].initial = user.is_active

        # Add Bootstrap classes
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            else:
                field.widget.attrs["class"] = "form-control"

    def save(self, commit=True):
        profile = super().save(commit=False)
        user = getattr(self, "user_instance", None)

        if user:
            user.username = self.cleaned_data["username"]
            user.email = self.cleaned_data["email"]
            user.first_name = self.cleaned_data.get("first_name", "")
            user.last_name = self.cleaned_data.get("last_name", "")
            user.is_active = self.cleaned_data.get("is_active", False)
            if commit:
                user.save()

        if commit:
            profile.save()

        return profile
