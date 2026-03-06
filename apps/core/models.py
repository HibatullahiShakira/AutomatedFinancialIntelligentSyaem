from django.db import models
import uuid
from django.contrib.auth.models import AbstractUser


class TenantAwareModel(models.Model):
    tenant_id = models.UUIDField(default=uuid.uuid4, db_index=True)

    class Meta:
        abstract = True


class Tenant(models.Model):
    """Business/organization that owns the account."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "tenants"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name


class User(AbstractUser):
    """
    Custom user model extending Django's AbstractUser.
    Users can belong to multiple tenants with different roles.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenants = models.ManyToManyField(
        Tenant,
        through="UserTenant",
        related_name="users",
        help_text="Tenants this user has access to"
    )
    # Email verification
    is_email_verified = models.BooleanField(default=False)
    # TOTP / MFA
    totp_secret = models.CharField(max_length=64, null=True, blank=True)
    totp_enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "users"

    def __str__(self) -> str:
        return self.email or self.username


class UserTenant(models.Model):
    """
    Junction table linking users to tenants with specific roles.
    A user can have different roles in different tenants.
    """
    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        ACCOUNTANT = "ACCOUNTANT", "Accountant"
        VIEWER = "VIEWER", "Viewer"
        SALESPERSON = "SALESPERSON", "Salesperson"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_tenants")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="tenant_users")
    role = models.CharField(max_length=20, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "user_tenants"
        unique_together = [["user", "tenant"]]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user.username} - {self.tenant.name} ({self.role})"


class RefreshToken(models.Model):
    """
    Stores refresh tokens for JWT authentication.
    Allows token revocation and tracking of active sessions.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="refresh_tokens")
    token = models.CharField(max_length=512, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    revoked = models.BooleanField(default=False)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "refresh_tokens"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Token for {self.user.username} (expires {self.expires_at})"

    @property
    def is_valid(self) -> bool:
        """Check if token is still valid (not expired, not revoked)."""
        from django.utils import timezone
        return not self.revoked and self.expires_at > timezone.now()


class LoginAttempt(models.Model):
    """
    Tracks login attempts for audit trail and brute-force analysis.
    Failed attempts are rate-limited at the view level (DRF throttling).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=150, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    success = models.BooleanField(default=False)
    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="login_attempts",
    )

    class Meta:
        db_table = "login_attempts"
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        status = "success" if self.success else "failure"
        return f"Login {status} for {self.username} at {self.timestamp}"


class MiddlewareTestModel(TenantAwareModel):
    """Test model for middleware and tenant isolation testing. Only used in tests."""
    name = models.CharField(max_length=100)

    class Meta:
        db_table = "core_middlewaretestmodel"


class Dummy(TenantAwareModel):
    """Minimal model to test multi-tenancy isolation. Only used in tests."""
    name = models.CharField(max_length=100)

    class Meta:
        db_table = "core_dummy"
        app_label = "core"
