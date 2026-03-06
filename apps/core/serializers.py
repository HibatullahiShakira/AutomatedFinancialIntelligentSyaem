"""
Serializers for authentication endpoints.
"""
from rest_framework import serializers
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from apps.core.models import User, Tenant, UserTenant


class UserRegistrationSerializer(serializers.Serializer):
    """Serializer for user registration."""
    email = serializers.EmailField(required=True)
    username = serializers.CharField(required=True, max_length=150)
    password = serializers.CharField(required=True, write_only=True, validators=[validate_password])
    first_name = serializers.CharField(required=False, max_length=150, allow_blank=True)
    last_name = serializers.CharField(required=False, max_length=150, allow_blank=True)
    tenant_name = serializers.CharField(required=True, max_length=255, help_text="Business/organization name")

    def validate_email(self, value: str) -> str:
        """Check if email already exists."""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("User with this email already exists.")
        return value

    def validate_username(self, value: str) -> str:
        """Check if username already exists."""
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("User with this username already exists.")
        return value

    def create(self, validated_data: dict) -> User:
        """Create user, tenant, and assign OWNER role."""
        tenant_name = validated_data.pop("tenant_name")
        
        # Create user
        user = User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=validated_data.get("first_name", ""),
            last_name=validated_data.get("last_name", ""),
        )
        
        # Create tenant (business)
        tenant = Tenant.objects.create(name=tenant_name)
        
        # Assign user as OWNER of tenant
        UserTenant.objects.create(
            user=user,
            tenant=tenant,
            role=UserTenant.Role.OWNER
        )
        
        return user


class LoginSerializer(serializers.Serializer):
    """Serializer for user login."""
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True)

    def validate(self, data: dict) -> dict:
        """Authenticate user credentials."""
        username = data.get("username")
        password = data.get("password")

        user = authenticate(username=username, password=password)
        
        if user is None:
            raise serializers.ValidationError("Invalid username or password.")
        
        if not user.is_active:
            raise serializers.ValidationError("User account is disabled.")
        
        data["user"] = user
        return data


class TokenRefreshSerializer(serializers.Serializer):
    """Serializer for token refresh."""
    refresh_token = serializers.CharField(required=True)


class UserSerializer(serializers.ModelSerializer):
    """Serializer for user details."""
    tenants = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "tenants"]

    def get_tenants(self, obj: User) -> list:
        """Get user's tenants with roles."""
        user_tenants = obj.user_tenants.filter(is_active=True).select_related("tenant")
        return [
            {
                "tenant_id": str(ut.tenant.id),
                "tenant_name": ut.tenant.name,
                "role": ut.role,
            }
            for ut in user_tenants
        ]


class TenantSerializer(serializers.ModelSerializer):
    """Serializer for tenant details."""
    
    class Meta:
        model = Tenant
        fields = ["id", "name", "created_at", "is_active"]
        read_only_fields = ["id", "created_at"]
