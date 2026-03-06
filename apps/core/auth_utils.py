"""
Authentication utilities for JWT token generation and validation.
"""
import jwt
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from django.conf import settings


def generate_access_token(user_id: uuid.UUID, tenant_id: Optional[uuid.UUID] = None) -> str:
    """
    Generate JWT access token (short-lived, 1 hour).

    Args:
        user_id: User's UUID
        tenant_id: Optional tenant UUID for tenant-scoped requests

    Returns:
        Encoded JWT token string
    """
    payload = {
        "user_id": str(user_id),
        "token_type": "access",
        "exp": datetime.utcnow() + timedelta(seconds=settings.JWT_ACCESS_TOKEN_LIFETIME),
        "iat": datetime.utcnow(),
    }

    if tenant_id:
        payload["tenant_id"] = str(tenant_id)

    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


def generate_refresh_token(user_id: uuid.UUID) -> str:
    """
    Generate JWT refresh token (long-lived, 7 days).

    Args:
        user_id: User's UUID

    Returns:
        Encoded JWT token string
    """
    payload = {
        "user_id": str(user_id),
        "token_type": "refresh",
        "exp": datetime.utcnow() + timedelta(seconds=settings.JWT_REFRESH_TOKEN_LIFETIME),
        "iat": datetime.utcnow(),
        "jti": str(uuid.uuid4()),  # Unique token ID for revocation
    }

    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate JWT token.

    Args:
        token: JWT token string

    Returns:
        Decoded token payload

    Raises:
        jwt.ExpiredSignatureError: Token has expired
        jwt.InvalidTokenError: Token is invalid
    """
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])


def verify_access_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify access token and return payload if valid.

    Args:
        token: JWT access token

    Returns:
        Token payload if valid, None otherwise
    """
    try:
        payload = decode_token(token)

        if payload.get("token_type") != "access":
            return None

        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def verify_refresh_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify refresh token and return payload if valid.

    Args:
        token: JWT refresh token

    Returns:
        Token payload if valid, None otherwise
    """
    try:
        payload = decode_token(token)

        if payload.get("token_type") != "refresh":
            return None

        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
