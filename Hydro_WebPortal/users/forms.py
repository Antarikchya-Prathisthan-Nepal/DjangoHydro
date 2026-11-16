import re
from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from .models import User

# ---------------------------------------------------------------------------
# Shared validators
# ---------------------------------------------------------------------------

# Matches common SQL injection patterns (case-insensitive).
_SQL_RE = re.compile(
    r"('|\")\s*;\s*"                    # '; or ";
    r"|--"                              # SQL line comment
    r"|/\*.*?\*/"                       # block comment
    r"|\b(OR|AND)\s+[\w'\"]+\s*=\s*[\w'\"]+"  # OR 1=1 / AND 'a'='a'
    r"|\bUNION\b.*\bSELECT\b"
    r"|\b(DROP|DELETE|TRUNCATE)\s+(TABLE|DATABASE|SCHEMA)\b"
    r"|\bINSERT\s+INTO\b"
    r"|\bUPDATE\b.*\bSET\b"
    r"|\bEXEC(UTE)?\s*\("
    r"|\bSLEEP\s*\("
    r"|\bBENCHMARK\s*\("
    r"|\bLOAD_FILE\s*\("
    r"|\bINTO\s+OUTFILE\b",
    re.IGNORECASE | re.DOTALL,
)

_NAME_RE = re.compile(r"^[A-Za-z\u00C0-\u024F\s'\-]+$")   # letters, spaces, hyphens, apostrophes
_PHONE_RE = re.compile(r"^[+\d\s\-().]{0,20}$")


def _reject_sql(value, field_name="This field"):
    if _SQL_RE.search(value):
        raise ValidationError(f"{field_name} contains invalid characters or patterns.")


_name_chars_validator = RegexValidator(
    _NAME_RE,
    "Only letters, spaces, hyphens, and apostrophes are allowed.",
)
_phone_validator = RegexValidator(
    _PHONE_RE,
    "Phone number may only contain digits, spaces, +, -, ( and ).",
)


class CustomLoginForm(AuthenticationForm):
    """Custom login form with styled fields"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({
            'class': 'form-input',
            'placeholder': 'Email or mobile number',
            'autocomplete': 'email'
        })
        self.fields['password'].widget.attrs.update({
            'class': 'form-input',
            'placeholder': 'Password',
            'autocomplete': 'current-password'
        })
    
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_approved:
            raise ValidationError(
                "This account is pending approval. Please contact the administrator.",
                code='unapproved',
            )


class UserRegistrationForm(UserCreationForm):
    """Form for user registration with additional fields"""

    first_name = forms.CharField(
        max_length=30, required=True,
        validators=[_name_chars_validator],
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name', 'style': 'color: white;'})
    )
    last_name = forms.CharField(
        max_length=30, required=True,
        validators=[_name_chars_validator],
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name', 'style': 'color: white;'})
    )
    email = forms.EmailField(
        max_length=254, required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email Address', 'style': 'color: white;'})
    )
    organization = forms.CharField(
        max_length=100, required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Organization', 'style': 'color: white;'})
    )
    phone_number = forms.CharField(
        max_length=20, required=False,
        validators=[_phone_validator],
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone Number (optional)', 'style': 'color: white;'})
    )
    
    from discharge_prediction.models import DischargeStation

    station = forms.ModelChoiceField(
        queryset=DischargeStation.objects.filter(is_active=True).order_by('name'),
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-control',
            'style': 'color: white;'
        }),
        label='Select Station'
    )

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'organization', 'phone_number', 'station', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Password',
            'style': 'color: white;'
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Confirm Password',
            'style': 'color: white;'
        })

    # -----------------------------------------------------------------------
    # Field-level clean methods
    # -----------------------------------------------------------------------

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        _reject_sql(email, "Email")
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email address already exists.")
        return email

    def clean_first_name(self):
        value = self.cleaned_data.get('first_name', '').strip()
        _reject_sql(value, "First name")
        return value

    def clean_last_name(self):
        value = self.cleaned_data.get('last_name', '').strip()
        _reject_sql(value, "Last name")
        return value

    def clean_organization(self):
        value = self.cleaned_data.get('organization', '').strip()
        _reject_sql(value, "Organization")
        if not value:
            raise ValidationError("Organization is required.")
        return value

    def clean_phone_number(self):
        value = self.cleaned_data.get('phone_number', '').strip()
        if value:
            _reject_sql(value, "Phone number")
        return value


class UserProfileForm(forms.ModelForm):
    """Form for updating user profile information"""
    
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'organization', 'phone_number')
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'organization': forms.TextInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
        }


class FreeRegistrationForm(UserCreationForm):
    """Lightweight registration for free-tier accounts (download access only).

    Only asks for name, email, and password — no organisation, phone, or station.
    Accounts created via this form are auto-approved on email verification.
    """

    first_name = forms.CharField(
        max_length=30, required=True,
        validators=[_name_chars_validator],
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'First Name', 'style': 'color: white;',
            'autocomplete': 'given-name',
        })
    )
    last_name = forms.CharField(
        max_length=30, required=True,
        validators=[_name_chars_validator],
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'Last Name', 'style': 'color: white;',
            'autocomplete': 'family-name',
        })
    )
    email = forms.EmailField(
        max_length=254, required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control', 'placeholder': 'Email Address', 'style': 'color: white;',
            'autocomplete': 'email',
        })
    )

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget.attrs.update({
            'class': 'form-control', 'placeholder': 'Password', 'style': 'color: white;',
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'form-control', 'placeholder': 'Confirm Password', 'style': 'color: white;',
        })

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        _reject_sql(email, 'Email')
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('An account with this email address already exists.')
        return email

    def clean_first_name(self):
        value = self.cleaned_data.get('first_name', '').strip()
        _reject_sql(value, 'First name')
        return value

    def clean_last_name(self):
        value = self.cleaned_data.get('last_name', '').strip()
        _reject_sql(value, 'Last name')
        return value
