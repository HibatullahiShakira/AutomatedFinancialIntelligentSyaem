"""
Authentication utilities: JWT tokens, TOTP/MFA, email verification, and token revocation.
"""
import jwt
import uuid
import pyotp
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from django.conf import settings
from django.core import signing
from django.core.cache import cache


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def generate_access_token(user_id: uuid.UUID, tenant_id: Optional[uuid.UUID] = None) -> str:
    """Generate JWT access token (short-lived, 1 hour). Includes jti for revocation."""
    payload: Dict[str, Any] = {
        "user_id": str(user_id),
        "token_type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(seconds=settings.JWT_ACCESS_TOKEN_LIFETIME),
        "iat": datetime.now(timezone.utc),
        "jti": str(uuid.uuid4()),
    }
    if tenant_id:
        payload["tenant_id"] = str(tenant_id)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


def generate_refresh_token(user_id: uuid.UUID) -> str:
    """Generate JWT refresh token (long-lived, 7 days)."""
    payload: Dict[str, Any] = {
        "user_id": str(user_id),
        "token_type": "refresh",
        "exp": datetime.now(timezone.utc) + timedelta(seconds=settings.JWT_REFRESH_TOKEN_LIFETIME),
        "iat": datetime.now(timezone.utc),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


def generate_mfa_token(user_id: uuid.UUID) -> str:
    """Generate short-lived MFA challenge token (5 min). Used in two-step TOTP login."""
    payload: Dict[str, Any] = {
        "user_id": str(user_id),
        "token_type": "mfa",
        "exp": datetime.now(timezone.utc) + timedelta(seconds=settings.JWT_MFA_TOKEN_LIFETIME),
        "iat": datetime.now(timezone.utc),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate JWT token.

    Raises:
        jwt.ExpiredSignatureError: Token has expired
        jwt.InvalidTokenError: Token is invalid
    """
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])


def verify_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify access token. Returns payload if valid and not revoked, None otherwise."""
    try:
        payload = decode_token(token)
        if payload.get("token_type") != "access":
            return None
        if is_access_token_revoked(payload):
            return None
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def verify_refresh_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify refresh token. Returns payload if valid, None otherwise."""
    try:
        payload = decode_token(token)
        if payload.get("token_type") != "refresh":
            return None
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def verify_mfa_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify MFA challenge token. Returns payload if valid, None otherwise."""
    try:
        payload = decode_token(token)
        if payload.get("token_type") != "mfa":
            return None
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


# ---------------------------------------------------------------------------
# Access token revocation via cache (plan: "Token revocation on logout stored in Redis")
# Uses Django's cache — LocMem in dev/test, Redis in production.
# ---------------------------------------------------------------------------

def revoke_access_token(payload: Dict[str, Any]) -> None:
    """Add access token's JTI to the revocation blacklist with TTL = remaining lifetime."""
    jti = payload.get("jti")
    exp = payload.get("exp")
    if not jti or not exp:
        return
    ttl = max(0, int(exp) - int(datetime.now(timezone.utc).timestamp()))
    if ttl > 0:
        cache.set(f"revoked_access:{jti}", "1", timeout=ttl)


def is_access_token_revoked(payload: Dict[str, Any]) -> bool:
    """Return True if this access token JTI has been revoked."""
    jti = payload.get("jti")
    if not jti:
        return False
    return cache.get(f"revoked_access:{jti}") is not None


# ---------------------------------------------------------------------------
# Email verification (using Django's signing framework — no extra model needed)
# ---------------------------------------------------------------------------

_EMAIL_VERIFICATION_SALT = "amss-email-verification"
_EMAIL_VERIFICATION_MAX_AGE = 86400  # 24 hours


def generate_email_verification_token(user_id: uuid.UUID) -> str:
    """Generate a signed token for email address verification (valid 24 hours)."""
    return signing.dumps(str(user_id), salt=_EMAIL_VERIFICATION_SALT)


def verify_email_verification_token(token: str) -> Optional[str]:
    """Verify email verification token. Returns user_id string on success, None on failure."""
    try:
        return signing.loads(token, salt=_EMAIL_VERIFICATION_SALT, max_age=_EMAIL_VERIFICATION_MAX_AGE)
    except (signing.SignatureExpired, signing.BadSignature):
        return None


# ---------------------------------------------------------------------------
# Password reset (using Django's built-in token generator)
# ---------------------------------------------------------------------------

def generate_password_reset_token(user: Any) -> str:
    """Return a url-safe '{uid_b64}.{token}' string for password reset emails."""
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.http import urlsafe_base64_encode
    from django.utils.encoding import force_bytes
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    return f"{uid}.{token}"


def verify_password_reset_token(token_str: str) -> Optional[Any]:
    """
    Verify a password reset token string ('{uid_b64}.{token}').
    Returns the User instance on success, None on failure.
    """
    from django.contrib.auth import get_user_model
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.http import urlsafe_base64_decode
    from django.utils.encoding import force_str
    User = get_user_model()
    try:
        uid_b64, token = token_str.split(".", 1)
        uid = force_str(urlsafe_base64_decode(uid_b64))
        user = User.objects.get(pk=uid)
        if default_token_generator.check_token(user, token):
            return user
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# TOTP / MFA (pyotp)
# ---------------------------------------------------------------------------

def generate_totp_secret() -> str:
    """Generate a random TOTP secret (base32-encoded, compatible with Google Authenticator)."""
    return pyotp.random_base32()


def get_totp_provisioning_uri(secret: str, user_email: str) -> str:
    """Return the otpauth:// URI; the client renders this as a QR code."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=user_email, issuer_name="AMSS")


def verify_totp_code(secret: str, code: str) -> bool:
    """Verify a 6-digit TOTP code. Allows ±1 time-step drift for clock skew."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)
