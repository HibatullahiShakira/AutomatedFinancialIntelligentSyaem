"""
Authentication API views.
"""
import logging
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from apps.core.models import RefreshToken, LoginAttempt, UserTenant
from apps.core.serializers import (
    UserRegistrationSerializer,
    LoginSerializer,
    TokenRefreshSerializer,
    UserSerializer,
    EmailVerificationSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    TOTPVerifySerializer,
    TOTPAuthSerializer,
)
from apps.core.auth_utils import (
    generate_access_token,
    generate_refresh_token,
    generate_mfa_token,
    verify_refresh_token,
    verify_mfa_token,
    revoke_access_token,
    generate_email_verification_token,
    verify_email_verification_token,
    generate_password_reset_token,
    verify_password_reset_token,
    generate_totp_secret,
    get_totp_provisioning_uri,
    verify_totp_code,
)

logger = logging.getLogger("amss.auth")


class LoginRateThrottle(AnonRateThrottle):
    scope = "login"


class RegisterRateThrottle(AnonRateThrottle):
    scope = "register"


def _get_client_ip(request) -> str:
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _log_login_attempt(username: str, ip: str, success: bool, user=None) -> None:
    LoginAttempt.objects.create(
        username=username,
        ip_address=ip or None,
        success=success,
        user=user,
    )
    if success:
        logger.info("Login success username=%s ip=%s", username, ip)
    else:
        logger.warning("Login failure username=%s ip=%s", username, ip)


def _send_verification_email(user) -> None:
    token = generate_email_verification_token(user.id)
    verify_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
    send_mail(
        subject="Verify your AMSS email address",
        message=f"Hi {user.first_name or user.username},\n\nVerify: {verify_url}\n\nExpires in 24 hours.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=True,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([RegisterRateThrottle])
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

    user_tenant = user.user_tenants.first()
    tenant_id = user_tenant.tenant.id if user_tenant else None

    access_token = generate_access_token(user.id, tenant_id)
    refresh_token_str = generate_refresh_token(user.id)

    RefreshToken.objects.create(
        user=user,
        token=refresh_token_str,
        expires_at=timezone.now() + timezone.timedelta(seconds=604800)
    )

    _send_verification_email(user)
    logger.info("User registered username=%s email=%s", user.username, user.email)

    return Response({
        "user": UserSerializer(user).data,
        "access_token": access_token,
        "refresh_token": refresh_token_str,
    }, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([AllowAny])
def verify_email(request):
    """
    Verify user's email address using the signed token from the verification email.

    POST /api/auth/verify-email/
    {"token": "..."}
    """
    serializer = EmailVerificationSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    from django.contrib.auth import get_user_model
    User = get_user_model()

    user_id = verify_email_verification_token(serializer.validated_data["token"])
    if not user_id:
        return Response({"error": "Invalid or expired verification token."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return Response({"error": "User not found."}, status=status.HTTP_400_BAD_REQUEST)

    if user.is_email_verified:
        return Response({"message": "Email already verified."}, status=status.HTTP_200_OK)

    user.is_email_verified = True
    user.save(update_fields=["is_email_verified"])
    logger.info("Email verified username=%s", user.username)
    return Response({"message": "Email verified successfully."}, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginRateThrottle])
def login(request):
    """
    Login with username/password.

    If user has TOTP enabled returns: {"mfa_required": true, "mfa_token": "..."}
    Otherwise returns: {access_token, refresh_token, user, mfa_warning}

    POST /api/auth/login/
    {"username": "username", "password": "password"}
    """
    serializer = LoginSerializer(data=request.data)
    ip = _get_client_ip(request)
    username = request.data.get("username", "")

    if not serializer.is_valid():
        _log_login_attempt(username, ip, success=False)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = serializer.validated_data["user"]

    if user.totp_enabled:
        # MFA required — issue short-lived challenge token instead of full auth
        mfa_token = generate_mfa_token(user.id)
        logger.info("MFA challenge issued username=%s ip=%s", username, ip)
        return Response({"mfa_required": True, "mfa_token": mfa_token}, status=status.HTTP_200_OK)

    _log_login_attempt(username, ip, success=True, user=user)

    user_tenant = user.user_tenants.filter(is_active=True).first()
    tenant_id = user_tenant.tenant.id if user_tenant else None

    access_token = generate_access_token(user.id, tenant_id)
    refresh_token_str = generate_refresh_token(user.id)

    RefreshToken.objects.create(
        user=user,
        token=refresh_token_str,
        expires_at=timezone.now() + timezone.timedelta(seconds=604800)
    )

    is_owner = user.user_tenants.filter(role=UserTenant.Role.OWNER, is_active=True).exists()

    return Response({
        "user": UserSerializer(user).data,
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "mfa_warning": is_owner and not user.totp_enabled,
    }, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([AllowAny])
def refresh_token(request):
    """
    Refresh access token using refresh token (with rotation).

    POST /api/auth/refresh/
    {"refresh_token": "..."}
    """
    serializer = TokenRefreshSerializer(data=request.data)

    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    refresh_token_str = serializer.validated_data["refresh_token"]

    payload = verify_refresh_token(refresh_token_str)
    if not payload:
        return Response({"error": "Invalid or expired refresh token"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        refresh_token_obj = RefreshToken.objects.get(token=refresh_token_str)
    except RefreshToken.DoesNotExist:
        return Response({"error": "Token not found"}, status=status.HTTP_400_BAD_REQUEST)

    if refresh_token_obj.revoked:
        return Response({"error": "Token has been revoked"}, status=status.HTTP_400_BAD_REQUEST)

    if not refresh_token_obj.is_valid:
        return Response({"error": "Token has been revoked or expired"}, status=status.HTTP_400_BAD_REQUEST)

    user = refresh_token_obj.user
    user_tenant = user.user_tenants.filter(is_active=True).first()
    tenant_id = user_tenant.tenant.id if user_tenant else None
    access_token = generate_access_token(user.id, tenant_id)

    # Rotate: revoke old token, issue new one
    refresh_token_obj.revoked = True
    refresh_token_obj.revoked_at = timezone.now()
    refresh_token_obj.save()

    new_refresh_token_str = generate_refresh_token(user.id)
    RefreshToken.objects.create(
        user=user,
        token=new_refresh_token_str,
        expires_at=timezone.now() + timezone.timedelta(seconds=604800)
    )

    return Response({
        "access_token": access_token,
        "refresh_token": new_refresh_token_str,
    }, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout(request):
    """
    Logout: revoke the refresh token and blacklist the current access token.

    POST /api/auth/logout/
    {"refresh_token": "..."}
    """
    refresh_token_str = request.data.get("refresh_token")

    if not refresh_token_str:
        return Response({"error": "refresh_token required"}, status=status.HTTP_400_BAD_REQUEST)

    # Blacklist current access token so it cannot be reused before expiry
    jwt_payload = getattr(request, "jwt_payload", None)
    if jwt_payload:
        revoke_access_token(jwt_payload)

    try:
        refresh_token_obj = RefreshToken.objects.get(token=refresh_token_str, user=request.user)
        refresh_token_obj.revoked = True
        refresh_token_obj.revoked_at = timezone.now()
        refresh_token_obj.save()
        logger.info("Logout user_id=%s", request.user.id)
        return Response(status=status.HTTP_204_NO_CONTENT)
    except RefreshToken.DoesNotExist:
        return Response({"error": "Token not found"}, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([AllowAny])
def forgot_password(request):
    """
    Request a password reset link. Always returns 200 to prevent email enumeration.

    POST /api/auth/forgot-password/
    {"email": "user@example.com"}
    """
    serializer = ForgotPasswordSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    from django.contrib.auth import get_user_model
    User = get_user_model()

    email = serializer.validated_data["email"]
    try:
        user = User.objects.get(email=email, is_active=True)
        token_str = generate_password_reset_token(user)
        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token_str}"
        send_mail(
            subject="Reset your AMSS password",
            message=f"Hi {user.first_name or user.username},\n\nReset: {reset_url}\n\nExpires in 1 hour.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )
        logger.info("Password reset requested email=%s", email)
    except User.DoesNotExist:
        pass  # Intentional: do not reveal whether the email exists

    return Response(
        {"message": "If that email exists, a reset link has been sent."},
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def reset_password(request):
    """
    Reset password using a valid reset token.

    POST /api/auth/reset-password/
    {"token": "...", "new_password": "..."}
    """
    serializer = ResetPasswordSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = verify_password_reset_token(serializer.validated_data["token"])
    if not user:
        return Response({"error": "Invalid or expired reset token."}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(serializer.validated_data["new_password"])
    user.save(update_fields=["password"])

    # Revoke all active refresh tokens for this user
    RefreshToken.objects.filter(user=user, revoked=False).update(
        revoked=True, revoked_at=timezone.now()
    )
    logger.info("Password reset completed user_id=%s", user.id)
    return Response({"message": "Password reset successfully."}, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# TOTP / MFA
# ---------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def totp_setup(request):
    """
    Initiate TOTP setup. Returns a secret and a provisioning URI for the authenticator app.
    Follow up with /api/auth/totp/verify/ to activate.

    POST /api/auth/totp/setup/
    (no body required)
    """
    user = request.user
    if user.totp_enabled:
        return Response({"error": "TOTP is already enabled."}, status=status.HTTP_400_BAD_REQUEST)

    secret = generate_totp_secret()
    user.totp_secret = secret
    user.save(update_fields=["totp_secret"])

    return Response({
        "secret": secret,
        "provisioning_uri": get_totp_provisioning_uri(secret, user.email),
        "message": "Scan the QR code, then call /api/auth/totp/verify/ with a code to activate.",
    }, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def totp_verify(request):
    """
    Verify a TOTP code to activate MFA for the authenticated user.

    POST /api/auth/totp/verify/
    {"code": "123456"}
    """
    serializer = TOTPVerifySerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    if not user.totp_secret:
        return Response(
            {"error": "TOTP setup not initiated. Call /api/auth/totp/setup/ first."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not verify_totp_code(user.totp_secret, serializer.validated_data["code"]):
        return Response({"error": "Invalid TOTP code."}, status=status.HTTP_400_BAD_REQUEST)

    user.totp_enabled = True
    user.save(update_fields=["totp_enabled"])
    logger.info("TOTP enabled user_id=%s", user.id)
    return Response({"message": "TOTP enabled. MFA is now required at login."}, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([AllowAny])
def totp_authenticate(request):
    """
    Complete MFA login by providing the TOTP code and the MFA challenge token.

    POST /api/auth/totp/authenticate/
    {"mfa_token": "...", "code": "123456"}
    """
    serializer = TOTPAuthSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    mfa_payload = verify_mfa_token(serializer.validated_data["mfa_token"])
    if not mfa_payload:
        return Response({"error": "Invalid or expired MFA token."}, status=status.HTTP_400_BAD_REQUEST)

    from django.contrib.auth import get_user_model
    User = get_user_model()

    try:
        user = User.objects.get(pk=mfa_payload["user_id"])
    except User.DoesNotExist:
        return Response({"error": "User not found."}, status=status.HTTP_400_BAD_REQUEST)

    ip = _get_client_ip(request)
    if not user.totp_secret or not verify_totp_code(user.totp_secret, serializer.validated_data["code"]):
        _log_login_attempt(user.username, ip, success=False, user=user)
        return Response({"error": "Invalid TOTP code."}, status=status.HTTP_400_BAD_REQUEST)

    _log_login_attempt(user.username, ip, success=True, user=user)

    user_tenant = user.user_tenants.filter(is_active=True).first()
    tenant_id = user_tenant.tenant.id if user_tenant else None

    access_token = generate_access_token(user.id, tenant_id)
    refresh_token_str = generate_refresh_token(user.id)

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
