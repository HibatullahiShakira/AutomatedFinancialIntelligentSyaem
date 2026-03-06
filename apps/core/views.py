"""
Authentication API views.
"""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from apps.core.models import User, RefreshToken
from apps.core.serializers import (
    UserRegistrationSerializer,
    LoginSerializer,
    TokenRefreshSerializer,
    UserSerializer,
)
from apps.core.auth_utils import (
    generate_access_token,
    generate_refresh_token,
    verify_refresh_token,
)


@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    """
    Register new user and create their business (tenant).
    
    POST /api/auth/register/
    {
        "email": "user@example.com",
        "username": "username",
        "password": "SecurePass123!",
        "first_name": "John",
        "last_name": "Doe",
        "tenant_name": "My Business Inc."
    }
    
    Returns:
        201: User created with access and refresh tokens
        400: Validation errors
    """
    serializer = UserRegistrationSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    user = serializer.save()
    
    # Get user's tenant (just created as OWNER)
    user_tenant = user.user_tenants.first()
    tenant_id = user_tenant.tenant.id if user_tenant else None
    
    # Generate tokens
    access_token = generate_access_token(user.id, tenant_id)
    refresh_token_str = generate_refresh_token(user.id)
    
    # Store refresh token in database
    RefreshToken.objects.create(
        user=user,
        token=refresh_token_str,
        expires_at=timezone.now() + timezone.timedelta(seconds=604800)  # 7 days
    )
    
    return Response({
        "user": UserSerializer(user).data,
        "access_token": access_token,
        "refresh_token": refresh_token_str,
    }, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    """
    Login user with username/password.
    
    POST /api/auth/login/
    {
        "username": "username",
        "password": "password"
    }
    
    Returns:
        200: Access and refresh tokens
        400: Invalid credentials
    """
    serializer = LoginSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    user = serializer.validated_data["user"]
    
    # Get user's first active tenant
    user_tenant = user.user_tenants.filter(is_active=True).first()
    tenant_id = user_tenant.tenant.id if user_tenant else None
    
    # Generate tokens
    access_token = generate_access_token(user.id, tenant_id)
    refresh_token_str = generate_refresh_token(user.id)
    
    # Store refresh token
    RefreshToken.objects.create(
        user=user,
        token=refresh_token_str,
        expires_at=timezone.now() + timezone.timedelta(seconds=604800)
    )
    
    return Response({
        "user": UserSerializer(user).data,
        "access_token": access_token,
        "refresh_token": refresh_token_str,
    }, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([AllowAny])
def refresh_token(request):
    """
    Refresh access token using refresh token.
    
    POST /api/auth/refresh/
    {
        "refresh_token": "..."
    }
    
    Returns:
        200: New access token
        400: Invalid or expired token
    """
    serializer = TokenRefreshSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    refresh_token_str = serializer.validated_data["refresh_token"]
    
    # Verify token
    payload = verify_refresh_token(refresh_token_str)
    if not payload:
        return Response(
            {"error": "Invalid or expired refresh token"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Check if token exists and is not revoked
    try:
        refresh_token_obj = RefreshToken.objects.get(token=refresh_token_str)
    except RefreshToken.DoesNotExist:
        return Response(
            {"error": "Token not found"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if not refresh_token_obj.is_valid:
        return Response(
            {"error": "Token has been revoked or expired"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Generate new access token
    user = refresh_token_obj.user
    user_tenant = user.user_tenants.filter(is_active=True).first()
    tenant_id = user_tenant.tenant.id if user_tenant else None
    
    access_token = generate_access_token(user.id, tenant_id)
    
    return Response({
        "access_token": access_token
    }, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout(request):
    """
    Logout user by revoking refresh token.
    
    POST /api/auth/logout/
    {
        "refresh_token": "..."
    }
    
    Returns:
        204: Token revoked successfully
        400: Invalid token
    """
    refresh_token_str = request.data.get("refresh_token")
    
    if not refresh_token_str:
        return Response(
            {"error": "refresh_token required"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        refresh_token_obj = RefreshToken.objects.get(
            token=refresh_token_str,
            user=request.user
        )
        refresh_token_obj.revoked = True
        refresh_token_obj.revoked_at = timezone.now()
        refresh_token_obj.save()
        
        return Response(status=status.HTTP_204_NO_CONTENT)
    except RefreshToken.DoesNotExist:
        return Response(
            {"error": "Token not found"},
            status=status.HTTP_400_BAD_REQUEST
        )
