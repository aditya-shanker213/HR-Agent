"""
Authentication dependencies for FastAPI routes.

Provides reusable dependencies for:
- Extracting JWT from Authorization header
- Verifying JWT token
- Loading current user from database
- Checking if user is active
- Role-based route protection

Usage:
    @router.get("/protected")
    async def protected_route(
        current_user = Depends(get_current_active_user)
    ):
        return {"user": current_user}
"""

from typing import Annotated, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.app.core.security import verify_access_token
from backend.app.database.mongo_connection import get_database
from backend.app.repositories.user_repository import UserRepository


security = HTTPBearer(auto_error=False)


ROLE_LEVELS = {
    "employee": 1,
    "manager": 2,
    "hr": 3,
    "admin": 4,
}


async def get_current_user(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)],
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> dict:
    """
    Get current authenticated user from JWT access token.

    Flow:
    1. Extract Bearer token from Authorization header
    2. Verify token signature and expiry
    3. Extract user ID from token payload
    4. Load user from MongoDB
    5. Return safe user data
    """

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Authorization header required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    payload = verify_access_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_repo = UserRepository(db)
    user = await user_repo.find_safe_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_active_user(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """
    Get current authenticated user and check account is active.
    """

    if not current_user.get("is_active", False):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is deactivated. Contact HR.",
        )

    return current_user


async def require_min_role(
    required_role: str,
    current_user: Annotated[dict, Depends(get_current_active_user)],
) -> dict:
    """
    Require minimum role level.

    Role hierarchy:
    employee < manager < hr < admin

    Example:
    - require_min_role("manager") allows manager, HR, admin
    - require_min_role("hr") allows HR, admin
    - require_min_role("admin") allows only admin
    """

    user_role = current_user.get("role")

    user_level = ROLE_LEVELS.get(user_role, 0)
    required_level = ROLE_LEVELS.get(required_role, 0)

    if user_level < required_level:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied. Required role: {required_role} or higher.",
        )

    return current_user


async def require_employee(
    current_user: Annotated[dict, Depends(get_current_active_user)],
) -> dict:
    """
    Require active employee account.

    All valid users have at least employee-level access.
    """

    return current_user


async def require_manager(
    current_user: Annotated[dict, Depends(get_current_active_user)],
) -> dict:
    """
    Require manager role or higher.
    """

    return await require_min_role("manager", current_user)


async def require_hr(
    current_user: Annotated[dict, Depends(get_current_active_user)],
) -> dict:
    """
    Require HR role or higher.
    """

    return await require_min_role("hr", current_user)


async def require_admin(
    current_user: Annotated[dict, Depends(get_current_active_user)],
) -> dict:
    """
    Require admin role.
    """

    return await require_min_role("admin", current_user)


async def get_token_payload(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)],
) -> dict:
    """
    Extract and verify token without loading user from database.

    Useful for:
    - request logging
    - rate limiting
    - lightweight token checks
    """

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = verify_access_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


async def get_optional_current_user(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)],
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> Optional[dict]:
    """
    Get current user if token is provided.

    If no token or invalid token is provided, return None.
    Useful for routes that support both public and logged-in users.
    """

    if not credentials:
        return None

    try:
        token = credentials.credentials
        payload = verify_access_token(token)

        if not payload:
            return None

        user_id = payload.get("sub")

        if not user_id:
            return None

        user_repo = UserRepository(db)
        user = await user_repo.find_safe_by_id(user_id)

        if not user:
            return None

        if not user.get("is_active", False):
            return None

        return user

    except Exception:
        return None