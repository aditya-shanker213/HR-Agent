"""
Authentication service - all auth business logic.

Handles:
- Signup with email OTP verification
- Login with username/password
- Forgot password with email OTP
- Password reset
- Access token and refresh token generation
- Refresh access token using refresh token
- Current user lookup from JWT

Pattern:
Route -> Auth Service -> User Repository -> MongoDB
                      -> OTP Service -> Redis
                      -> Security Utils -> Bcrypt/JWT
                      -> Email Service -> SMTP/provider
"""

from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from pymongo.errors import DuplicateKeyError

from backend.app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_access_token,
    verify_refresh_token,
    verify_password,
)
from backend.app.models.user_model import UserRole
from backend.app.repositories.user_repository import UserRepository
from backend.app.utils.otp import OTPService, OtpPurpose


class AuthService:
    """
    Authentication service handling all auth operations.

    Routes should call this service.
    This service should call repositories, OTP service, security utils, and email service.
    """

    def __init__(
        self,
        user_repo: UserRepository,
        otp_service: OTPService,
        email_service: Optional[Any] = None,
        expose_otp_for_testing: bool = False,
    ):
        self.user_repo = user_repo
        self.otp_service = otp_service
        self.email_service = email_service
        self.expose_otp_for_testing = expose_otp_for_testing

    # -------------------------
    # Internal helpers
    # -------------------------

    def _normalize_username(self, username: str) -> str:
        """Normalize username for case-insensitive use."""
        return username.strip().lower()

    def _normalize_email(self, email: str) -> str:
        """Normalize email for case-insensitive use."""
        return email.strip().lower()

    def _safe_user_response(self, user: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return safe user data for API response.

        Never expose:
        - password_hash
        - failed_login_attempts
        - locked_until
        - internal security fields
        """
        return {
            "id": user.get("_id") or user.get("id"),
            "username": user.get("username"),
            "email": user.get("email"),
            "phone": user.get("phone"),
            "role": user.get("role"),
            "is_active": user.get("is_active", True),
            "is_email_verified": user.get("is_email_verified", False),
            "is_phone_verified": user.get("is_phone_verified", False),
        }

    async def _send_otp_email(self, email: str, otp: str, purpose: str) -> None:
        """
        Send OTP using email service.

        During local development, if email_service is not configured,
        OTP can be exposed only when expose_otp_for_testing=True.
        """

        if not self.email_service:
            if self.expose_otp_for_testing:
                return

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Email service is not configured. Cannot send OTP.",
            )

        if purpose == OtpPurpose.SIGNUP:
            subject = "Verify your HR AI Agent account"
            body = (
                f"Your signup OTP is {otp}.\n\n"
                "This OTP will expire in 10 minutes.\n"
                "If you did not request this, please ignore this email."
            )

        elif purpose == OtpPurpose.FORGOT_PASSWORD:
            subject = "Reset your HR AI Agent password"
            body = (
                f"Your password reset OTP is {otp}.\n\n"
                "This OTP will expire in 10 minutes.\n"
                "If you did not request this, please ignore this email."
            )

        else:
            subject = "Your HR AI Agent OTP"
            body = (
                f"Your OTP is {otp}.\n\n"
                "This OTP will expire soon.\n"
                "If you did not request this, please ignore this email."
            )

        sent = await self.email_service.send_email(
            to_email=email,
            subject=subject,
            body=body,
        )

        if not sent and not self.expose_otp_for_testing:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to send OTP email. Please try again later.",
            )

    # -------------------------
    # Signup flow
    # -------------------------

    async def send_signup_otp(
        self,
        username: str,
        email: str,
        password: str,
    ) -> Dict[str, Any]:
        """
        Send OTP for signup email verification.

        Important:
        User is not created here.
        User is created only after OTP verification.
        """
        username = self._normalize_username(username)
        email = self._normalize_email(email)

        if await self.user_repo.username_exists(username):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken",
            )

        if await self.user_repo.email_exists(email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

        rate_limit = await self.otp_service.check_rate_limit(
            identifier=email,
            purpose=OtpPurpose.SIGNUP,
            max_requests=3,
            window_minutes=15,
        )

        if not rate_limit["allowed"]:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many OTP requests. Please try again later.",
            )

        otp = self.otp_service.generate_otp()

        await self.otp_service.store_otp(
            identifier=email,
            otp=otp,
            purpose=OtpPurpose.SIGNUP,
            expiry_minutes=10,
        )

        await self._send_otp_email(
            email=email,
            otp=otp,
            purpose=OtpPurpose.SIGNUP,
        )

        response = {
            "message": "OTP sent successfully to your email",
            "email": email,
            "expires_in_minutes": 10,
        }

        # Local testing only. Keep False in real/staging/production.
        if self.expose_otp_for_testing:
            response["dev_otp"] = otp

        return response

    async def verify_signup_otp(
        self,
        username: str,
        email: str,
        password: str,
        otp: str,
    ) -> Dict[str, Any]:
        """
        Verify OTP and create user account.
        """
        username = self._normalize_username(username)
        email = self._normalize_email(email)

        verification = await self.otp_service.verify_otp(
            identifier=email,
            otp=otp,
            purpose=OtpPurpose.SIGNUP,
        )

        if not verification["valid"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=verification["error"],
            )

        # Double check because username/email may be taken
        # between send_signup_otp and verify_signup_otp.
        if await self.user_repo.username_exists(username):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken",
            )

        if await self.user_repo.email_exists(email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

        password_hash = hash_password(password)

        user_data = {
            "username": username,
            "email": email,
            "password_hash": password_hash,
            "role": UserRole.EMPLOYEE.value,
            "is_active": True,
            "is_email_verified": True,
            "is_phone_verified": False,
            "failed_login_attempts": 0,
            "locked_until": None,
            "password_updated_at": datetime.utcnow(),
        }

        try:
            user_id = await self.user_repo.create_user(user_data)
        except DuplicateKeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username or email already exists",
            )

        user = await self.user_repo.find_by_id(user_id)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Account created but failed to load user data",
            )

        return {
            "message": "Account created successfully",
            "user": self._safe_user_response(user),
        }

    # -------------------------
    # Login flow
    # -------------------------

    async def login(
        self,
        username: str,
        password: str,
    ) -> Dict[str, Any]:
        """
        Login with username and password.

        Current UI uses username.
        Later you can switch to find_by_identifier() to support username OR email.
        """
        username = self._normalize_username(username)

        user = await self.user_repo.find_by_username(username)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            )

        if not user.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is deactivated. Contact HR.",
            )

        locked_until = user.get("locked_until")
        if locked_until and locked_until > datetime.utcnow():
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Account is temporarily locked due to multiple failed login attempts.",
            )

        if not verify_password(password, user["password_hash"]):
            await self.user_repo.increment_failed_login(username)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            )

        await self.user_repo.update_last_login(username)

        access_token = create_access_token(
            subject=user["_id"],
            role=user["role"],
            extra_data={
                "username": user["username"],
                "email": user["email"],
            },
        )

        refresh_token = create_refresh_token(
            subject=user["_id"],
            role=user["role"],
            extra_data={
                "username": user["username"],
            },
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": self._safe_user_response(user),
        }

    # -------------------------
    # Refresh token flow
    # -------------------------

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """
        Create a new access token using a valid refresh token.

        Use case:
        Access token expires, frontend sends refresh token,
        backend returns a new access token.
        """
        payload = verify_refresh_token(refresh_token)

        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user_id = payload.get("sub")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token payload",
            )

        user = await self.user_repo.find_by_id(user_id)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )

        if not user.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is deactivated",
            )

        access_token = create_access_token(
            subject=user["_id"],
            role=user["role"],
            extra_data={
                "username": user["username"],
                "email": user["email"],
            },
        )

        return {
            "access_token": access_token,
            "token_type": "bearer",
        }

    # -------------------------
    # Forgot password flow
    # -------------------------

    async def send_forgot_password_otp(
        self,
        email: str,
    ) -> Dict[str, Any]:
        """
        Send OTP for password reset.

        Security rule:
        Do not reveal whether email exists.
        """
        email = self._normalize_email(email)

        user = await self.user_repo.find_by_email(email)

        # Do not reveal whether email exists.
        if not user:
            return {
                "message": "If this email is registered, you will receive an OTP",
                "email": email,
                "expires_in_minutes": 10,
            }

        rate_limit = await self.otp_service.check_rate_limit(
            identifier=email,
            purpose=OtpPurpose.FORGOT_PASSWORD,
            max_requests=3,
            window_minutes=15,
        )

        if not rate_limit["allowed"]:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many OTP requests. Please try again later.",
            )

        otp = self.otp_service.generate_otp()

        await self.otp_service.store_otp(
            identifier=email,
            otp=otp,
            purpose=OtpPurpose.FORGOT_PASSWORD,
            expiry_minutes=10,
        )

        await self._send_otp_email(
            email=email,
            otp=otp,
            purpose=OtpPurpose.FORGOT_PASSWORD,
        )

        response = {
            "message": "If this email is registered, you will receive an OTP",
            "email": email,
            "expires_in_minutes": 10,
        }

        # Local testing only. Keep False in real/staging/production.
        if self.expose_otp_for_testing:
            response["dev_otp"] = otp

        return response

    async def reset_password(
        self,
        email: str,
        otp: str,
        new_password: str,
    ) -> Dict[str, Any]:
        """
        Reset password after OTP verification.
        """
        email = self._normalize_email(email)

        verification = await self.otp_service.verify_otp(
            identifier=email,
            otp=otp,
            purpose=OtpPurpose.FORGOT_PASSWORD,
        )

        if not verification["valid"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=verification["error"],
            )

        user = await self.user_repo.find_by_email(email)

        # Keep response generic for security.
        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid password reset request",
            )

        password_hash = hash_password(new_password)

        updated = await self.user_repo.update_password(email, password_hash)

        if not updated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update password",
            )

        return {
            "message": "Password reset successfully. Please login with your new password."
        }

    # -------------------------
    # Current user flow
    # -------------------------

    async def get_current_user(self, token: str) -> Dict[str, Any]:
        """
        Get current user from JWT access token.

        Used by:
        - auth dependency
        - auth middleware
        - protected APIs
        """
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
            )

        user = await self.user_repo.find_by_id(user_id)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )

        if not user.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is deactivated",
            )

        return self._safe_user_response(user)