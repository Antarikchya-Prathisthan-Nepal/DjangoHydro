from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils import timezone
from datetime import timedelta
import uuid
from discharge_prediction.models import DischargeStation


class UserManager(BaseUserManager):
    """Define a model manager for User model with no username field."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        """Create and save a User with the given email and password."""
        if not email:
            raise ValueError('The given email must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a regular User with the given email and password."""
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        """Create and save a SuperUser with the given email and password."""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Custom User model with email as the unique identifier instead of username"""
    
    username = None
    email = models.EmailField('email address', unique=True)
    organization = models.CharField(max_length=255, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    is_approved = models.BooleanField(default=False, help_text="Designates whether this user's registration has been approved.")
    email_verified = models.BooleanField(default=True, help_text="Designates whether this user has verified their email address.")
    account_tier = models.CharField(
        max_length=10,
        choices=[('free', 'Free'), ('full', 'Full')],
        default='full',
        help_text=(
            "'free' — auto-approved on email verification; can download delineation & watershed reports. "
            "'full' — requires admin approval; unlocks the Discharge Prediction module."
        ),
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.email


class StationAccess(models.Model):
    """Model to track which users have access to which discharge stations"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='station_accesses')
    station = models.ForeignKey(DischargeStation, on_delete=models.CASCADE, related_name='user_accesses')
    access_level = models.CharField(max_length=20, choices=[
        ('viewer', 'Viewer'),
        ('editor', 'Editor'),
        ('admin', 'Administrator')
    ], default='viewer')
    granted_at = models.DateTimeField(auto_now_add=True)
    granted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='granted_accesses')
    
    class Meta:
        unique_together = ['user', 'station']
        verbose_name = "Station Access"
        verbose_name_plural = "Station Accesses"

    def __str__(self):
        return f"{self.user.email} - {self.station.name} ({self.access_level})"


class PendingRegistration(models.Model):
    """Temporarily stores registration data until the email address is verified.
    A User account is only created after the verification link is clicked."""
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=30)
    organization = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=20, blank=True)
    tier = models.CharField(
        max_length=10,
        choices=[('free', 'Free'), ('full', 'Full')],
        default='full',
    )
    station = models.ForeignKey(
        DischargeStation, on_delete=models.CASCADE,
        null=True, blank=True,
        help_text="Required for full-tier registrations only.",
    )
    password_hash = models.CharField(max_length=255)  # pre-hashed with make_password
    created_at = models.DateTimeField(auto_now_add=True)

    def is_valid(self):
        """Pending registration expires after 24 hours."""
        return timezone.now() < self.created_at + timedelta(hours=24)

    def __str__(self):
        return f"Pending registration for {self.email}"


class EmailVerificationToken(models.Model):
    """One-time token for verifying a user's email address."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='email_verification_token')
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_valid(self):
        """Token expires after 24 hours."""
        return timezone.now() < self.created_at + timedelta(hours=24)

    def __str__(self):
        return f"Verification token for {self.user.email}"


class AccessRequest(models.Model):
    """A free-tier user's request to be upgraded to full-tier / given station access."""

    STATUS_PENDING  = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES  = [
        (STATUS_PENDING,  'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    user           = models.ForeignKey(User, on_delete=models.CASCADE, related_name='access_requests')
    organization   = models.CharField(max_length=255, help_text="User's organisation")
    contact_number = models.CharField(max_length=20, help_text="Contact phone number")
    message        = models.TextField(help_text="Why does the user need full-tier access?")
    station        = models.ForeignKey(
        DischargeStation, on_delete=models.SET_NULL,
        null=True, blank=True,
        help_text="Station the user is interested in (optional).",
    )
    status     = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at  = models.DateTimeField(null=True, blank=True)
    reviewed_by  = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reviewed_access_requests',
    )
    admin_note = models.TextField(blank=True, help_text="Internal note visible only to admins.")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Access Request"
        verbose_name_plural = "Access Requests"

    def __str__(self):
        return f"Access request by {self.user.email} [{self.status}]"
