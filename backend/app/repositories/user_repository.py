"""
User repository - all MongoDB operations for the users collection.

This repository handles authentication user accounts:
- username
- email
- password_hash
- role
- account status
- login security fields

It is separate from employee_repository.py, which handles HR employment data:
- department
- manager_id
- leave balance
- claim limits
- payroll mapping
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError


class UserRepository:
    """
    Repository for users collection.

    Pattern:
    Route -> Service -> Repository -> MongoDB

    Routes and services should not write Motor queries directly.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.users

    # -------------------------
    # Internal helpers
    # -------------------------

    def _normalize_username(self, username: str) -> str:
        return username.strip().lower()

    def _normalize_email(self, email: str) -> str:
        return email.strip().lower()

    def _normalize_phone(self, phone: Optional[str]) -> Optional[str]:
        if not phone:
            return None
        return phone.strip().replace(" ", "")

    def _convert_id(self, user: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Convert MongoDB ObjectId to string before returning."""
        if user and "_id" in user:
            user["_id"] = str(user["_id"])
        return user

    def _safe_projection(self) -> Dict[str, int]:
        """Fields that should not be returned in safe user reads."""
        return {
            "password_hash": 0,
            "failed_login_attempts": 0,
            "locked_until": 0,
        }

    # -------------------------
    # Find methods
    # -------------------------

    async def find_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Find a user by username."""
        user = await self.collection.find_one(
            {"username": self._normalize_username(username)}
        )
        return self._convert_id(user)

    async def find_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Find a user by email."""
        user = await self.collection.find_one(
            {"email": self._normalize_email(email)}
        )
        return self._convert_id(user)

    async def find_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """Find a user by phone number. Useful later for phone OTP."""
        user = await self.collection.find_one(
            {"phone": self._normalize_phone(phone)}
        )
        return self._convert_id(user)

    async def find_by_identifier(self, identifier: str) -> Optional[Dict[str, Any]]:
        """
        Find a user by username or email.

        Useful if later you want login using either:
        - username
        - email
        """
        value = identifier.strip().lower()

        user = await self.collection.find_one(
            {
                "$or": [
                    {"username": value},
                    {"email": value},
                ]
            }
        )

        return self._convert_id(user)

    async def find_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Find a user by MongoDB _id."""
        try:
            object_id = ObjectId(user_id)
        except InvalidId:
            return None

        user = await self.collection.find_one({"_id": object_id})
        return self._convert_id(user)

    async def find_safe_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Find user by id without sensitive fields."""
        try:
            object_id = ObjectId(user_id)
        except InvalidId:
            return None

        user = await self.collection.find_one(
            {"_id": object_id},
            self._safe_projection()
        )

        return self._convert_id(user)

    # -------------------------
    # Create user
    # -------------------------

    async def create_user(self, user_data: Dict[str, Any]) -> str:
        """
        Create a new user.

        Returns:
            Created user's _id as string.

        Raises:
            DuplicateKeyError if username/email unique index is violated.
        """
        now = datetime.utcnow()

        user_data["username"] = self._normalize_username(user_data["username"])
        user_data["email"] = self._normalize_email(user_data["email"])

        if "phone" in user_data:
            user_data["phone"] = self._normalize_phone(user_data.get("phone"))

        user_data.setdefault("role", "employee")
        user_data.setdefault("is_active", True)
        user_data.setdefault("is_email_verified", False)
        user_data.setdefault("is_phone_verified", False)
        user_data.setdefault("failed_login_attempts", 0)
        user_data.setdefault("locked_until", None)
        user_data.setdefault("password_updated_at", now)

        user_data["created_at"] = now
        user_data["updated_at"] = now

        try:
            result = await self.collection.insert_one(user_data)
            return str(result.inserted_id)
        except DuplicateKeyError:
            raise

    # -------------------------
    # Update auth/security fields
    # -------------------------

    async def update_password(self, email: str, password_hash: str) -> bool:
        """
        Update user's password hash.
        Used for password reset flow.
        """
        now = datetime.utcnow()

        result = await self.collection.update_one(
            {"email": self._normalize_email(email)},
            {
                "$set": {
                    "password_hash": password_hash,
                    "password_updated_at": now,
                    "updated_at": now,
                    "failed_login_attempts": 0,
                    "locked_until": None,
                }
            },
        )

        return result.matched_count > 0

    async def mark_email_verified(self, email: str) -> bool:
        """Mark user's email as verified after OTP confirmation."""
        result = await self.collection.update_one(
            {"email": self._normalize_email(email)},
            {
                "$set": {
                    "is_email_verified": True,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        return result.matched_count > 0

    async def mark_phone_verified(self, phone: str) -> bool:
        """Mark phone as verified. Useful later for phone OTP."""
        result = await self.collection.update_one(
            {"phone": self._normalize_phone(phone)},
            {
                "$set": {
                    "is_phone_verified": True,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        return result.matched_count > 0

    async def update_last_login(self, username: str) -> bool:
        """
        Update user's last login timestamp.
        Also resets failed login attempts after successful login.
        """
        result = await self.collection.update_one(
            {"username": self._normalize_username(username)},
            {
                "$set": {
                    "last_login": datetime.utcnow(),
                    "failed_login_attempts": 0,
                    "locked_until": None,
                }
            },
        )

        return result.matched_count > 0

    async def increment_failed_login(
        self,
        username: str,
        max_attempts: int = 5,
        lock_minutes: int = 15,
    ) -> bool:
        """
        Increment failed login attempts.

        If attempts reach max_attempts, lock account temporarily.
        """
        username = self._normalize_username(username)
        user = await self.collection.find_one({"username": username})

        if not user:
            return False

        failed_attempts = int(user.get("failed_login_attempts", 0)) + 1

        update_data: Dict[str, Any] = {
            "failed_login_attempts": failed_attempts,
            "updated_at": datetime.utcnow(),
        }

        if failed_attempts >= max_attempts:
            update_data["locked_until"] = datetime.utcnow() + timedelta(
                minutes=lock_minutes
            )

        result = await self.collection.update_one(
            {"username": username},
            {"$set": update_data},
        )

        return result.matched_count > 0

    async def clear_account_lock(self, username: str) -> bool:
        """Manually clear account lock and failed attempts."""
        result = await self.collection.update_one(
            {"username": self._normalize_username(username)},
            {
                "$set": {
                    "failed_login_attempts": 0,
                    "locked_until": None,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        return result.matched_count > 0

    # -------------------------
    # Admin/user management
    # -------------------------

    async def deactivate_user(self, username: str) -> bool:
        """Deactivate a user account."""
        result = await self.collection.update_one(
            {"username": self._normalize_username(username)},
            {
                "$set": {
                    "is_active": False,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        return result.matched_count > 0

    async def activate_user(self, username: str) -> bool:
        """Reactivate a user account."""
        result = await self.collection.update_one(
            {"username": self._normalize_username(username)},
            {
                "$set": {
                    "is_active": True,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        return result.matched_count > 0

    async def update_role(self, username: str, new_role: str) -> bool:
        """
        Update user's role.

        Role validation should happen in service layer before calling this.
        """
        result = await self.collection.update_one(
            {"username": self._normalize_username(username)},
            {
                "$set": {
                    "role": new_role,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        return result.matched_count > 0

    async def update_user_profile_fields(
        self,
        username: str,
        update_data: Dict[str, Any],
    ) -> bool:
        """
        Update safe user account fields.

        Do not use this for password updates.
        """
        blocked_fields = {
            "_id",
            "password_hash",
            "failed_login_attempts",
            "locked_until",
            "created_at",
        }

        safe_update = {
            key: value
            for key, value in update_data.items()
            if key not in blocked_fields
        }

        if "email" in safe_update:
            safe_update["email"] = self._normalize_email(safe_update["email"])

        if "phone" in safe_update:
            safe_update["phone"] = self._normalize_phone(safe_update["phone"])

        if not safe_update:
            return False

        safe_update["updated_at"] = datetime.utcnow()

        result = await self.collection.update_one(
            {"username": self._normalize_username(username)},
            {"$set": safe_update},
        )

        return result.matched_count > 0

    # -------------------------
    # Existence checks
    # -------------------------

    async def username_exists(self, username: str) -> bool:
        """Check if username already exists."""
        count = await self.collection.count_documents(
            {"username": self._normalize_username(username)}
        )
        return count > 0

    async def email_exists(self, email: str) -> bool:
        """Check if email already exists."""
        count = await self.collection.count_documents(
            {"email": self._normalize_email(email)}
        )
        return count > 0

    async def phone_exists(self, phone: str) -> bool:
        """Check if phone number already exists. Useful later for phone OTP."""
        normalized_phone = self._normalize_phone(phone)

        if not normalized_phone:
            return False

        count = await self.collection.count_documents(
            {"phone": normalized_phone}
        )
        return count > 0

    # -------------------------
    # List/count users
    # -------------------------

    async def get_all_users(self, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get all users for admin panel.

        Never returns password_hash or internal security fields.
        """
        limit = min(limit, 100)

        cursor = (
            self.collection.find({}, self._safe_projection())
            .skip(skip)
            .limit(limit)
            .sort("created_at", -1)
        )

        users = await cursor.to_list(length=limit)

        for user in users:
            user["_id"] = str(user["_id"])

        return users

    async def count_users(self) -> int:
        """Get total number of users."""
        return await self.collection.count_documents({})

    async def count_active_users(self) -> int:
        """Get total number of active users."""
        return await self.collection.count_documents({"is_active": True})