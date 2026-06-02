"""
Company Settings repository - all MongoDB operations for company_settings collection.

Pattern:
Route → Service → Repository → MongoDB

This repository handles:
- Create/initialize company settings
- Read company settings
- Update company settings
- Update specific configuration sections
- Patch nested configuration sections
- Activate/deactivate settings
- Settings existence checks
- Lightweight summary helpers

Important:
- Usually single document per company with company_id="default"
- Can be extended for multi-tenant companies later
- Routes should not write MongoDB queries
- Services should not write MongoDB queries
- All company_settings collection queries should go through this repository

Note:
Unlike normal master data collections, this is usually a singleton pattern.
There is usually only one active settings document for the default company.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError


class CompanySettingsRepository:
    """
    Repository for company_settings collection.

    This handles global HR configuration storage.
    Typically maintains a single document per company.
    """

    BLOCKED_UPDATE_FIELDS = {
        "_id",
        "id",
        "company_id",
        "created_at",
        "created_by",
    }

    OPTIONAL_TEXT_FIELDS = {
        "created_by",
        "updated_by",
    }

    VALID_SECTION_NAMES = {
        "company_info",
        "system",
        "work_week",
        "leave_policy",
        "payroll",
        "claim_policy",
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.company_settings

    # -------------------------
    # Internal helpers
    # -------------------------

    def _normalize_company_id(self, company_id: Optional[str] = "default") -> str:
        """
        Normalize company_id.

        Rules:
        - default if missing
        - lowercase
        - allow letters, numbers, hyphen, underscore
        """
        if not company_id:
            return "default"

        normalized = str(company_id).strip().lower()

        if not normalized:
            return "default"

        if not normalized.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                "company_id can contain only letters, numbers, hyphen, and underscore"
            )

        return normalized

    def _normalize_optional_text(self, value: Optional[str]) -> Optional[str]:
        """
        Strip optional text and convert empty string to None.
        """
        if value is None:
            return None

        value = str(value).strip()
        return value or None

    def _to_object_id(self, value: str) -> Optional[ObjectId]:
        """
        Safely convert string ID to MongoDB ObjectId.
        """
        try:
            return ObjectId(str(value))
        except (InvalidId, TypeError):
            return None

    def _convert_id(
        self,
        document: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Convert MongoDB ObjectId to string.

        Keeps both:
        - _id for internal consistency
        - id for API/service convenience
        """
        if document and "_id" in document:
            document["_id"] = str(document["_id"])
            document["id"] = document["_id"]

        return document

    def _clean_insert_data(self, settings_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize settings data before insert.
        """
        cleaned = dict(settings_data)

        cleaned["company_id"] = self._normalize_company_id(
            cleaned.get("company_id", "default")
        )

        for field in self.OPTIONAL_TEXT_FIELDS:
            if field in cleaned:
                cleaned[field] = self._normalize_optional_text(cleaned[field])

        cleaned.setdefault("is_active", True)

        now = datetime.utcnow()
        cleaned["created_at"] = now
        cleaned["updated_at"] = now

        return cleaned

    def _clean_update_data(self, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove fields that should never be updated directly.
        Normalize optional text fields.
        """
        cleaned: Dict[str, Any] = {}

        for key, value in update_data.items():
            if key in self.BLOCKED_UPDATE_FIELDS:
                continue

            cleaned[key] = value

        for field in self.OPTIONAL_TEXT_FIELDS:
            if field in cleaned:
                cleaned[field] = self._normalize_optional_text(cleaned[field])

        cleaned["updated_at"] = datetime.utcnow()

        return cleaned

    def _flatten_dict(
        self,
        data: Dict[str, Any],
        parent_key: str = "",
    ) -> Dict[str, Any]:
        """
        Flatten nested dictionary for MongoDB dot-notation updates.

        Example:
            {"work_week": {"working_hours_per_day": 8}}
        becomes:
            {"work_week.working_hours_per_day": 8}
        """
        flattened: Dict[str, Any] = {}

        for key, value in data.items():
            new_key = f"{parent_key}.{key}" if parent_key else key

            if isinstance(value, dict):
                flattened.update(self._flatten_dict(value, new_key))
            else:
                flattened[new_key] = value

        return flattened

    # -------------------------
    # Create / Initialize
    # -------------------------

    async def create(self, settings_data: Dict[str, Any]) -> str:
        """
        Create company settings.

        Typically called once during initial setup.

        Returns:
            Created settings _id as string.

        Raises:
            DuplicateKeyError if company_id already exists.
        """
        cleaned_data = self._clean_insert_data(settings_data)

        try:
            result = await self.collection.insert_one(cleaned_data)
            return str(result.inserted_id)
        except DuplicateKeyError:
            raise

    async def initialize_default_settings(
        self,
        company_name: str,
        email: str,
        address_line1: str,
        city: str,
        state: str,
        pincode: str,
        created_by: Optional[str] = None,
        company_id: str = "default",
    ) -> str:
        """
        Initialize company settings with minimal required information.

        All other sections should be added by model/service defaults.
        """
        settings_data = {
            "company_id": self._normalize_company_id(company_id),
            "company_info": {
                "company_name": company_name,
                "email": email,
                "address_line1": address_line1,
                "city": city,
                "state": state,
                "pincode": pincode,
                "country": "India",
            },
            "created_by": created_by,
            "updated_by": created_by,
        }

        return await self.create(settings_data)

    async def get_or_create_default_settings(
        self,
        settings_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Return active default company settings if present.
        Otherwise create settings using provided data and return created document.

        Useful during first-time setup.
        """
        company_id = self._normalize_company_id(
            settings_data.get("company_id", "default")
        )

        existing = await self.find_by_company_id(company_id)

        if existing:
            return existing

        settings_id = await self.create(settings_data)
        created = await self.find_by_id(settings_id)

        if created is None:
            raise RuntimeError("Company settings created but failed to retrieve")

        return created

    # -------------------------
    # Read operations
    # -------------------------

    async def find_by_id(self, settings_id: str) -> Optional[Dict[str, Any]]:
        """
        Find company settings by MongoDB _id.
        """
        object_id = self._to_object_id(settings_id)

        if object_id is None:
            return None

        settings = await self.collection.find_one({"_id": object_id})
        return self._convert_id(settings)

    async def find_by_company_id(
        self,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Find active company settings by company_id.

        This is the most common query because the system usually has one active
        settings document for the default company.
        """
        normalized_company_id = self._normalize_company_id(company_id)

        settings = await self.collection.find_one(
            {
                "company_id": normalized_company_id,
                "is_active": True,
            }
        )

        return self._convert_id(settings)

    async def find_any_by_company_id(
        self,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Find company settings by company_id regardless of active status.

        Useful for activate/deactivate and admin recovery screens.
        """
        normalized_company_id = self._normalize_company_id(company_id)

        settings = await self.collection.find_one(
            {
                "company_id": normalized_company_id,
            }
        )

        return self._convert_id(settings)

    async def get_active_settings(self) -> Optional[Dict[str, Any]]:
        """
        Get the active default company settings.
        """
        return await self.find_by_company_id("default")

    async def get_summary(
        self,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Get lightweight company settings summary.

        Useful for dashboard/header/service quick checks.
        """
        settings = await self.find_by_company_id(company_id)

        if not settings:
            return None

        company_info = settings.get("company_info", {})
        system = settings.get("system", {})
        work_week = settings.get("work_week", {})
        leave_policy = settings.get("leave_policy", {})
        payroll = settings.get("payroll", {})

        return {
            "id": settings.get("id") or settings.get("_id"),
            "company_id": settings.get("company_id", "default"),
            "company_name": company_info.get("company_name"),
            "currency": payroll.get("currency", "INR"),
            "pay_cycle": payroll.get("pay_cycle", "monthly"),
            "timezone": system.get("timezone", "Asia/Kolkata"),
            "leave_year_start_month": leave_policy.get("leave_year_start_month", 1),
            "financial_year_start_month": payroll.get("financial_year_start_month", 4),
            "probation_period_days": leave_policy.get("probation_period_days", 90),
            "working_days": work_week.get(
                "working_days",
                ["monday", "tuesday", "wednesday", "thursday", "friday"],
            ),
            "weekend_days": work_week.get("weekend_days", ["saturday", "sunday"]),
            "is_active": settings.get("is_active", False),
        }

    async def exists_by_company_id(
        self,
        company_id: str = "default",
    ) -> bool:
        """
        Check if company settings exist for a company.
        """
        normalized_company_id = self._normalize_company_id(company_id)

        count = await self.collection.count_documents(
            {"company_id": normalized_company_id},
            limit=1,
        )

        return count > 0

    async def active_exists_by_company_id(
        self,
        company_id: str = "default",
    ) -> bool:
        """
        Check if active company settings exist for a company.
        """
        normalized_company_id = self._normalize_company_id(company_id)

        count = await self.collection.count_documents(
            {
                "company_id": normalized_company_id,
                "is_active": True,
            },
            limit=1,
        )

        return count > 0

    async def exists_by_id(self, settings_id: str) -> bool:
        """
        Check whether settings exist by ID.
        """
        object_id = self._to_object_id(settings_id)

        if object_id is None:
            return False

        count = await self.collection.count_documents(
            {"_id": object_id},
            limit=1,
        )

        return count > 0

    # -------------------------
    # Get specific sections
    # -------------------------

    async def get_company_info(
        self,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Get only company information.

        Used for reports, letters, salary slips, and documents.
        """
        settings = await self.find_by_company_id(company_id)

        if not settings:
            return None

        return settings.get("company_info")

    async def get_system_config(
        self,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Get only system-level HR configuration.
        """
        settings = await self.find_by_company_id(company_id)

        if not settings:
            return None

        return settings.get("system")

    async def get_work_week_config(
        self,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Get only work week configuration.

        Useful for leave and payroll working-day calculations.
        """
        settings = await self.find_by_company_id(company_id)

        if not settings:
            return None

        return settings.get("work_week")

    async def get_leave_policy_config(
        self,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Get only leave policy configuration.

        Used by leave management service.
        """
        settings = await self.find_by_company_id(company_id)

        if not settings:
            return None

        return settings.get("leave_policy")

    async def get_payroll_config(
        self,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Get only payroll configuration.

        Used by payroll service.
        """
        settings = await self.find_by_company_id(company_id)

        if not settings:
            return None

        return settings.get("payroll")

    async def get_claim_policy_config(
        self,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Get only claim policy configuration.

        Used by claims service.
        """
        settings = await self.find_by_company_id(company_id)

        if not settings:
            return None

        return settings.get("claim_policy")

    async def get_section(
        self,
        section_name: str,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Get a specific settings section dynamically.
        """
        if section_name not in self.VALID_SECTION_NAMES:
            raise ValueError(
                f"Invalid section_name. Must be one of: {', '.join(sorted(self.VALID_SECTION_NAMES))}"
            )

        settings = await self.find_by_company_id(company_id)

        if not settings:
            return None

        return settings.get(section_name)

    # -------------------------
    # Update
    # -------------------------

    async def update(
        self,
        settings_id: str,
        update_data: Dict[str, Any],
    ) -> bool:
        """
        Update company settings fields.

        Can update full document or selected top-level sections.

        Returns:
            True if settings exist and update operation matched it.
        """
        object_id = self._to_object_id(settings_id)

        if object_id is None:
            return False

        safe_update = self._clean_update_data(update_data)

        if not safe_update:
            return False

        result = await self.collection.update_one(
            {"_id": object_id},
            {"$set": safe_update},
        )

        return result.matched_count > 0

    async def patch(
        self,
        settings_id: str,
        update_data: Dict[str, Any],
    ) -> bool:
        """
        Patch company settings using MongoDB dot notation.

        Useful for nested partial updates.
        Example:
            {"work_week": {"working_hours_per_day": 7.5}}
        updates only:
            work_week.working_hours_per_day
        """
        object_id = self._to_object_id(settings_id)

        if object_id is None:
            return False

        safe_update = self._clean_update_data(update_data)

        if not safe_update:
            return False

        flattened_update = self._flatten_dict(safe_update)

        result = await self.collection.update_one(
            {"_id": object_id},
            {"$set": flattened_update},
        )

        return result.matched_count > 0

    async def update_by_company_id(
        self,
        company_id: str,
        update_data: Dict[str, Any],
    ) -> bool:
        """
        Update company settings by company_id.

        More convenient than using MongoDB ObjectId.
        """
        settings = await self.find_any_by_company_id(company_id)

        if not settings:
            return False

        settings_id = settings.get("id") or settings.get("_id")
        return await self.update(settings_id, update_data)

    async def patch_by_company_id(
        self,
        company_id: str,
        update_data: Dict[str, Any],
    ) -> bool:
        """
        Patch company settings by company_id using dot notation.
        """
        settings = await self.find_any_by_company_id(company_id)

        if not settings:
            return False

        settings_id = settings.get("id") or settings.get("_id")
        return await self.patch(settings_id, update_data)

    async def update_section(
        self,
        section_name: str,
        section_data: Dict[str, Any],
        company_id: str = "default",
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Replace one full settings section.

        Example:
            update_section("work_week", {...})
        """
        if section_name not in self.VALID_SECTION_NAMES:
            raise ValueError(
                f"Invalid section_name. Must be one of: {', '.join(sorted(self.VALID_SECTION_NAMES))}"
            )

        update_data: Dict[str, Any] = {
            section_name: section_data,
        }

        if updated_by:
            update_data["updated_by"] = self._normalize_optional_text(updated_by)

        return await self.update_by_company_id(company_id, update_data)

    async def patch_section(
        self,
        section_name: str,
        section_data: Dict[str, Any],
        company_id: str = "default",
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Partially update one settings section.

        Example:
            patch_section("work_week", {"working_hours_per_day": 7.5})
        updates:
            work_week.working_hours_per_day
        """
        if section_name not in self.VALID_SECTION_NAMES:
            raise ValueError(
                f"Invalid section_name. Must be one of: {', '.join(sorted(self.VALID_SECTION_NAMES))}"
            )

        update_data: Dict[str, Any] = {
            section_name: section_data,
        }

        if updated_by:
            update_data["updated_by"] = self._normalize_optional_text(updated_by)

        return await self.patch_by_company_id(company_id, update_data)

    async def update_company_info(
        self,
        company_info_data: Dict[str, Any],
        company_id: str = "default",
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Replace only company information.
        """
        return await self.update_section(
            section_name="company_info",
            section_data=company_info_data,
            company_id=company_id,
            updated_by=updated_by,
        )

    async def update_system_config(
        self,
        system_data: Dict[str, Any],
        company_id: str = "default",
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Replace only system configuration.
        """
        return await self.update_section(
            section_name="system",
            section_data=system_data,
            company_id=company_id,
            updated_by=updated_by,
        )

    async def update_work_week(
        self,
        work_week_data: Dict[str, Any],
        company_id: str = "default",
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Replace only work week configuration.
        """
        return await self.update_section(
            section_name="work_week",
            section_data=work_week_data,
            company_id=company_id,
            updated_by=updated_by,
        )

    async def update_leave_policy(
        self,
        leave_policy_data: Dict[str, Any],
        company_id: str = "default",
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Replace only leave policy configuration.
        """
        return await self.update_section(
            section_name="leave_policy",
            section_data=leave_policy_data,
            company_id=company_id,
            updated_by=updated_by,
        )

    async def update_payroll(
        self,
        payroll_data: Dict[str, Any],
        company_id: str = "default",
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Replace only payroll configuration.
        """
        return await self.update_section(
            section_name="payroll",
            section_data=payroll_data,
            company_id=company_id,
            updated_by=updated_by,
        )

    async def update_claim_policy(
        self,
        claim_policy_data: Dict[str, Any],
        company_id: str = "default",
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Replace only claim policy configuration.
        """
        return await self.update_section(
            section_name="claim_policy",
            section_data=claim_policy_data,
            company_id=company_id,
            updated_by=updated_by,
        )

    # -------------------------
    # Activate / Deactivate
    # -------------------------

    async def deactivate(
        self,
        settings_id: str,
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Deactivate company settings.

        Be careful:
        Other services depend on active company settings.
        Service layer should decide whether deactivation is allowed.
        """
        object_id = self._to_object_id(settings_id)

        if object_id is None:
            return False

        update_data: Dict[str, Any] = {
            "is_active": False,
            "updated_at": datetime.utcnow(),
        }

        if updated_by:
            update_data["updated_by"] = self._normalize_optional_text(updated_by)

        result = await self.collection.update_one(
            {"_id": object_id},
            {"$set": update_data},
        )

        return result.matched_count > 0

    async def activate(
        self,
        settings_id: str,
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Reactivate company settings.
        """
        object_id = self._to_object_id(settings_id)

        if object_id is None:
            return False

        update_data: Dict[str, Any] = {
            "is_active": True,
            "updated_at": datetime.utcnow(),
        }

        if updated_by:
            update_data["updated_by"] = self._normalize_optional_text(updated_by)

        result = await self.collection.update_one(
            {"_id": object_id},
            {"$set": update_data},
        )

        return result.matched_count > 0

    async def deactivate_by_company_id(
        self,
        company_id: str = "default",
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Deactivate company settings by company_id.
        """
        settings = await self.find_any_by_company_id(company_id)

        if not settings:
            return False

        settings_id = settings.get("id") or settings.get("_id")
        return await self.deactivate(settings_id, updated_by=updated_by)

    async def activate_by_company_id(
        self,
        company_id: str = "default",
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Activate company settings by company_id.
        """
        settings = await self.find_any_by_company_id(company_id)

        if not settings:
            return False

        settings_id = settings.get("id") or settings.get("_id")
        return await self.activate(settings_id, updated_by=updated_by)

    # -------------------------
    # Validation helpers
    # -------------------------

    async def has_settings_configured(
        self,
        company_id: str = "default",
    ) -> bool:
        """
        Check if company has active configured settings.

        Returns True if settings exist and are active.
        Other services can use this to ensure settings are available.
        """
        settings = await self.find_by_company_id(company_id)

        if not settings:
            return False

        return settings.get("is_active", False)

    async def count_settings(self) -> int:
        """
        Count company settings documents.

        Useful for setup screens and admin diagnostics.
        """
        return await self.collection.count_documents({})