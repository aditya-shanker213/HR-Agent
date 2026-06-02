"""
OTP (One-Time Password) generation and verification utilities.

Uses Redis for temporary OTP storage with automatic expiry.
Stores hashed OTPs, not plain OTPs.

Supported OTP purposes:
- signup
- forgot_password
- step_up_auth
- phone_verification
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import redis.asyncio as redis


class OtpPurpose:
    """Allowed OTP purposes."""

    SIGNUP = "signup"
    FORGOT_PASSWORD = "forgot_password"
    STEP_UP_AUTH = "step_up_auth"
    PHONE_VERIFICATION = "phone_verification"


class OTPService:
    """
    OTP generation and verification service.

    Flow:
    1. Generate OTP
    2. Store hashed OTP in Redis
    3. Send plain OTP to email/phone from auth_service or notification service
    4. Verify user-entered OTP
    5. Delete OTP after successful verification or after expiry
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        otp_length: int = 6,
        max_attempts: int = 5,
        expiry_minutes: int = 10,
    ):
        self.redis = redis_client
        self.otp_length = otp_length
        self.max_attempts = max_attempts
        self.expiry_minutes = expiry_minutes

    # -------------------------
    # Internal helpers
    # -------------------------

    def _normalize_identifier(self, identifier: str) -> str:
        """
        Normalize email or phone identifier.

        For email:
        - remove leading/trailing spaces
        - lowercase

        For phone:
        - remove leading/trailing spaces
        - keep original digits/+ format
        """
        return identifier.strip().lower()

    def _otp_key(self, identifier: str, purpose: str) -> str:
        """Build Redis key for OTP storage."""
        normalized = self._normalize_identifier(identifier)
        return f"otp:{purpose}:{normalized}"

    def _rate_limit_key(self, identifier: str, purpose: str) -> str:
        """Build Redis key for OTP rate limit."""
        normalized = self._normalize_identifier(identifier)
        return f"otp_rate_limit:{purpose}:{normalized}"

    def _to_str(self, value: Any, default: str = "") -> str:
        """Convert Redis bytes/string value safely to string."""
        if value is None:
            return default

        if isinstance(value, bytes):
            return value.decode()

        return str(value)

    # -------------------------
    # OTP generation/hash
    # -------------------------

    def generate_otp(self) -> str:
        """
        Generate a secure random numeric OTP.

        Example:
        483921
        """
        digits = "0123456789"
        return "".join(secrets.choice(digits) for _ in range(self.otp_length))

    def hash_otp(self, otp: str) -> str:
        """
        Hash OTP before storing in Redis.

        We store only hash, not plain OTP.
        """
        return hashlib.sha256(otp.encode("utf-8")).hexdigest()

    # -------------------------
    # OTP storage
    # -------------------------

    async def store_otp(
        self,
        identifier: str,
        otp: str,
        purpose: str,
        expiry_minutes: Optional[int] = None,
    ) -> bool:
        """
        Store OTP hash in Redis with expiry.

        Args:
            identifier: Email or phone number
            otp: Plain OTP. It will be hashed before storage.
            purpose: signup, forgot_password, step_up_auth, etc.
            expiry_minutes: Optional custom expiry time.

        Returns:
            True if stored successfully.
        """
        redis_key = self._otp_key(identifier, purpose)
        otp_hash = self.hash_otp(otp)

        otp_data = {
            "otp_hash": otp_hash,
            "attempts": "0",
            "created_at": datetime.utcnow().isoformat(),
            "purpose": purpose,
        }

        expiry = expiry_minutes or self.expiry_minutes
        expiry_seconds = expiry * 60

        await self.redis.hset(redis_key, mapping=otp_data)
        await self.redis.expire(redis_key, expiry_seconds)

        return True

    # -------------------------
    # OTP verification
    # -------------------------

    async def verify_otp(
        self,
        identifier: str,
        otp: str,
        purpose: str,
    ) -> Dict[str, Any]:
        """
        Verify OTP against stored hash.

        Returns:
            {
                "valid": bool,
                "error": str | None,
                "attempts_remaining": int
            }
        """
        redis_key = self._otp_key(identifier, purpose)

        exists = await self.redis.exists(redis_key)
        if not exists:
            return {
                "valid": False,
                "error": "OTP expired or not found. Please request a new OTP.",
                "attempts_remaining": 0,
            }

        otp_data = await self.redis.hgetall(redis_key)

        stored_hash = self._to_str(
            otp_data.get("otp_hash") or otp_data.get(b"otp_hash")
        )

        attempts_raw = self._to_str(
            otp_data.get("attempts") or otp_data.get(b"attempts"),
            default="0",
        )

        try:
            attempts = int(attempts_raw)
        except ValueError:
            attempts = 0

        if attempts >= self.max_attempts:
            await self.redis.delete(redis_key)
            return {
                "valid": False,
                "error": "Maximum OTP attempts exceeded. Please request a new OTP.",
                "attempts_remaining": 0,
            }

        provided_hash = self.hash_otp(otp)

        if hmac.compare_digest(provided_hash, stored_hash):
            await self.redis.delete(redis_key)
            return {
                "valid": True,
                "error": None,
                "attempts_remaining": self.max_attempts - attempts,
            }

        attempts += 1
        await self.redis.hset(redis_key, "attempts", attempts)

        attempts_left = max(self.max_attempts - attempts, 0)

        if attempts_left == 0:
            await self.redis.delete(redis_key)
            return {
                "valid": False,
                "error": "Maximum OTP attempts exceeded. Please request a new OTP.",
                "attempts_remaining": 0,
            }

        return {
            "valid": False,
            "error": f"Invalid OTP. {attempts_left} attempts remaining.",
            "attempts_remaining": attempts_left,
        }

    async def delete_otp(self, identifier: str, purpose: str) -> bool:
        """
        Delete OTP manually.

        Useful after successful signup, password reset, or user cancellation.
        """
        redis_key = self._otp_key(identifier, purpose)
        deleted = await self.redis.delete(redis_key)
        return deleted > 0

    # -------------------------
    # Rate limiting
    # -------------------------

    async def check_rate_limit(
        self,
        identifier: str,
        purpose: str,
        max_requests: int = 3,
        window_minutes: int = 15,
    ) -> Dict[str, Any]:
        """
        Check whether OTP request is allowed.

        Example:
        Maximum 3 OTP sends per email per 15 minutes.
        """
        redis_key = self._rate_limit_key(identifier, purpose)

        current = await self.redis.get(redis_key)

        if current is None:
            await self.redis.set(redis_key, 1, ex=window_minutes * 60)
            return {
                "allowed": True,
                "remaining": max_requests - 1,
                "reset_at": datetime.utcnow() + timedelta(minutes=window_minutes),
            }

        try:
            count = int(self._to_str(current, default="0"))
        except ValueError:
            count = 0

        if count >= max_requests:
            ttl = await self.redis.ttl(redis_key)

            if ttl is None or ttl < 0:
                ttl = window_minutes * 60

            return {
                "allowed": False,
                "remaining": 0,
                "reset_at": datetime.utcnow() + timedelta(seconds=ttl),
            }

        await self.redis.incr(redis_key)

        ttl = await self.redis.ttl(redis_key)
        if ttl is None or ttl < 0:
            ttl = window_minutes * 60

        return {
            "allowed": True,
            "remaining": max_requests - count - 1,
            "reset_at": datetime.utcnow() + timedelta(seconds=ttl),
        }

    async def get_otp_ttl(self, identifier: str, purpose: str) -> int:
        """
        Get remaining OTP expiry time in seconds.

        Useful if frontend wants to show countdown.
        """
        redis_key = self._otp_key(identifier, purpose)
        ttl = await self.redis.ttl(redis_key)

        if ttl is None or ttl < 0:
            return 0

        return ttl