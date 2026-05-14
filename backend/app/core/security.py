"""
Security utilities for password hashing and JWT token generation.

All cryptographic operations are kept here:
- Password hashing using bcrypt
- Password verification
- JWT access token creation
- JWT refresh token creation
- JWT token verification

No other file should contain crypto logic.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from jose import JWTError, ExpiredSignatureError, jwt
from passlib.context import CryptContext

from backend.app.core.config import settings


# Password hashing configuration
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """
    Hash a plain password using bcrypt.

    Never store plain passwords in MongoDB.
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against the stored password hash.
    """
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    subject: str,
    role: str,
    extra_data: Optional[Dict[str, Any]] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a JWT access token.

    Args:
        subject: User ID or username. Prefer user_id.
        role: User role such as employee, manager, hr, admin.
        extra_data: Optional extra safe claims.
        expires_delta: Optional custom expiry time.

    Returns:
        Encoded JWT access token.
    """
    now = datetime.utcnow()

    expire = now + (
        expires_delta
        if expires_delta
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    payload: Dict[str, Any] = {
        "sub": subject,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": expire,
    }

    if extra_data:
        payload.update(extra_data)

    return jwt.encode(
        payload,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_refresh_token(
    subject: str,
    role: str,
    extra_data: Optional[Dict[str, Any]] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a JWT refresh token.

    Refresh token should live longer than access token.
    """
    now = datetime.utcnow()

    expire = now + (
        expires_delta
        if expires_delta
        else timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )

    payload: Dict[str, Any] = {
        "sub": subject,
        "role": role,
        "type": "refresh",
        "iat": now,
        "exp": expire,
    }

    if extra_data:
        payload.update(extra_data)

    return jwt.encode(
        payload,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def verify_access_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify and decode access token.

    Returns decoded payload if valid.
    Returns None if invalid, expired, or not an access token.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )

        if payload.get("type") != "access":
            return None

        return payload

    except ExpiredSignatureError:
        return None
    except JWTError:
        return None


def verify_refresh_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify and decode refresh token.

    Returns decoded payload if valid.
    Returns None if invalid, expired, or not a refresh token.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )

        if payload.get("type") != "refresh":
            return None

        return payload

    except ExpiredSignatureError:
        return None
    except JWTError:
        return None


def decode_token_without_type_check(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode any valid token without checking token type.

    Use this only for debugging or internal utility cases.
    Do not use it for protected API authentication.
    """
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError:
        return None