"""
Authentication routes.

All authentication endpoints:
- POST /auth/signup/send-otp
- POST /auth/signup/verify
- POST /auth/login
- POST /auth/forgot-password/send-otp
- POST /auth/reset-password
- POST /auth/refresh-token
- GET /auth/me

Pattern:
Route -> Auth Service -> Repository/OTP Service/Email Service
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.app.core.config import settings
from backend.app.database.mongo_connection import get_database
from backend.app.database.redis_connection import get_redis_dependency
from backend.app.dependencies.auth_dependencies import get_current_active_user
from backend.app.notifications.email_service import get_email_service
from backend.app.repositories.user_repository import UserRepository
from backend.app.schemas.auth_schema import (
    ForgotPasswordOtpRequest,
    LoginRequest,
    LoginResponse,
    OtpResponse,
    PasswordResetResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    ResetPasswordRequest,
    SafeUserResponse,
    SignupOtpRequest,
    SignupResponse,
    SignupVerifyRequest,
)
from backend.app.services.auth_service import AuthService
from backend.app.utils.otp import OTPService


router = APIRouter(prefix="/auth", tags=["Authentication"])


# -------------------------
# Dependency injection
# -------------------------

async def get_auth_service(
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis_client=Depends(get_redis_dependency),
) -> AuthService:
    """
    Create AuthService instance with all dependencies.

    Dependencies:
    - UserRepository uses MongoDB
    - OTPService uses Redis
    - EmailService sends OTP emails
    """

    user_repo = UserRepository(db)

    otp_service = OTPService(
        redis_client=redis_client,
        otp_length=settings.OTP_LENGTH,
        max_attempts=settings.OTP_MAX_ATTEMPTS,
        expiry_minutes=settings.OTP_EXPIRE_MINUTES,
    )

    email_service = get_email_service()

    return AuthService(
        user_repo=user_repo,
        otp_service=otp_service,
        email_service=email_service,
        expose_otp_for_testing=settings.EXPOSE_OTP_FOR_TESTING,
    )


# -------------------------
# Signup flow routes
# -------------------------

@router.post(
    "/signup/send-otp",
    response_model=OtpResponse,
    status_code=status.HTTP_200_OK,
    summary="Send OTP for signup",
    description=(
        "Send email OTP for signup verification. "
        "User account is created only after OTP verification."
    ),
)
async def send_signup_otp(
    request: SignupOtpRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    """
    Send OTP for signup email verification.

    User is not created at this step.
    """

    result = await auth_service.send_signup_otp(
        username=request.username,
        email=request.email,
        password=request.password,
    )

    return OtpResponse(
        message=result["message"],
        email=result["email"],
        expires_in_minutes=result["expires_in_minutes"],
        dev_otp=result.get("dev_otp"),
    )


@router.post(
    "/signup/verify",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Verify OTP and create account",
    description="Verify signup OTP and create user account.",
)
async def verify_signup_otp(
    request: SignupVerifyRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    """
    Verify OTP and create user account.
    """

    result = await auth_service.verify_signup_otp(
        username=request.username,
        email=request.email,
        password=request.password,
        otp=request.otp,
    )

    return SignupResponse(
        message=result["message"],
        user=result["user"],
    )


# -------------------------
# Login route
# -------------------------

@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Login with username and password",
    description="Login with username and password. Returns access token and refresh token.",
)
async def login(
    request: LoginRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    """
    Login with username and password.
    """

    result = await auth_service.login(
        username=request.username,
        password=request.password,
    )

    return LoginResponse(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        token_type=result["token_type"],
        user=result["user"],
    )


# -------------------------
# Forgot password flow routes
# -------------------------

@router.post(
    "/forgot-password/send-otp",
    response_model=OtpResponse,
    status_code=status.HTTP_200_OK,
    summary="Send OTP for password reset",
    description=(
        "Send email OTP for password reset. "
        "Response does not reveal whether email exists."
    ),
)
async def send_forgot_password_otp(
    request: ForgotPasswordOtpRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    """
    Send OTP for forgot password flow.
    """

    result = await auth_service.send_forgot_password_otp(
        email=request.email,
    )

    return OtpResponse(
        message=result["message"],
        email=result["email"],
        expires_in_minutes=result["expires_in_minutes"],
        dev_otp=result.get("dev_otp"),
    )


@router.post(
    "/reset-password",
    response_model=PasswordResetResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset password with OTP",
    description="Reset password after OTP verification.",
)
async def reset_password(
    request: ResetPasswordRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    """
    Reset password with OTP verification.
    """

    result = await auth_service.reset_password(
        email=request.email,
        otp=request.otp,
        new_password=request.new_password,
    )

    return PasswordResetResponse(
        message=result["message"],
    )


# -------------------------
# Refresh token route
# -------------------------

@router.post(
    "/refresh-token",
    response_model=RefreshTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh access token",
    description="Create a new access token using a valid refresh token.",
)
async def refresh_access_token(
    request: RefreshTokenRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    """
    Refresh access token using refresh token.
    """

    result = await auth_service.refresh_access_token(
        refresh_token=request.refresh_token,
    )

    return RefreshTokenResponse(
        access_token=result["access_token"],
        token_type=result["token_type"],
    )


# -------------------------
# Current user route
# -------------------------

@router.get(
    "/me",
    response_model=SafeUserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current user",
    description="Get current authenticated user. Requires valid access token.",
)
async def get_me(
    current_user: Annotated[dict, Depends(get_current_active_user)],
):
    """
    Get current authenticated user.

    Requires:
    Authorization: Bearer <access_token>
    """

    return current_user