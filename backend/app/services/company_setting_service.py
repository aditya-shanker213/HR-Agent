"""
Company Settings service - Business logic for company configuration.

Pattern:
Route → Service → Repository → MongoDB

This service handles:
- Creating/initializing company settings
- Retrieving settings and specific sections
- Updating full settings or specific sections
- Patching partial nested updates
- Activating/deactivating settings
- Full merged validation before database write

Important:
- Routes should handle HTTP request/response and role dependencies.
- Service should handle business rules and validation.
- Repository should handle MongoDB operations only.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, ValidationError
from pymongo.errors import DuplicateKeyError

from backend.app.models.company_setting_model import CompanySettings
from backend.app.repositories.company_settings_repository import (
    CompanySettingsRepository,
)
from backend.app.schemas.company_setting_schema import (
    ClaimPolicyConfigSchema,
    CompanyInfoSchema,
    CompanySettingsCreatedResponse,
    CompanySettingsExistsResponse,
    CompanySettingsInitializedResponse,
    CompanySettingsResponse,
    CompanySettingsSectionResponse,
    CompanySettingsStatusResponse,
    CompanySettingsSummaryResponse,
    CompanySettingsUpdatedResponse,
    CreateCompanySettingsRequest,
    InitializeCompanySettingsRequest,
    LeavePolicyConfigSchema,
    PatchClaimPolicyRequest,
    PatchCompanyInfoRequest,
    PatchCompanySettingsRequest,
    PatchLeavePolicyRequest,
    PatchPayrollRequest,
    PatchSystemConfigRequest,
    PatchWorkWeekRequest,
    PayrollConfigSchema,
    SystemConfigSchema,
    UpdateClaimPolicyRequest,
    UpdateCompanyInfoRequest,
    UpdateCompanySettingsRequest,
    UpdateLeavePolicyRequest,
    UpdatePayrollRequest,
    UpdateSystemConfigRequest,
    UpdateWorkWeekRequest,
    WorkWeekConfigSchema,
)


class CompanySettingsService:
    """
    Service layer for company settings operations.

    This service protects the singleton/global configuration document from
    invalid updates by always validating the complete merged settings payload
    before saving changes.
    """

    VALID_SECTION_NAMES = {
        "company_info",
        "system",
        "work_week",
        "leave_policy",
        "payroll",
        "claim_policy",
    }

    def __init__(
        self,
        db: Optional[AsyncIOMotorDatabase] = None,
        repository: Optional[CompanySettingsRepository] = None,
    ):
        """
        Initialize service.

        You can pass:
        - db: normal route dependency usage
        - repository: useful for tests/mocking
        """
        if repository is not None:
            self.repository = repository
            return

        if db is None:
            raise ValueError("Either db or repository must be provided")

        self.repository = CompanySettingsRepository(db)

    # -------------------------
    # Internal helpers
    # -------------------------

    def _normalize_company_id(self, company_id: Optional[str] = "default") -> str:
        """
        Normalize company_id.

        Rules:
        - default if missing
        - lowercase
        - letters, numbers, hyphen, underscore only
        """
        if not company_id:
            return "default"

        company_id = str(company_id).strip().lower()

        if not company_id:
            return "default"

        if not company_id.replace("_", "").replace("-", "").isalnum():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "company_id can contain only letters, numbers, hyphen, "
                    "and underscore"
                ),
            )

        return company_id

    def _model_to_dict(
        self,
        value: Any,
        exclude_none: bool = False,
        exclude_unset: bool = False,
    ) -> Dict[str, Any]:
        """
        Convert Pydantic model or dict to plain dict.
        """
        if isinstance(value, BaseModel):
            return value.model_dump(
                exclude_none=exclude_none,
                exclude_unset=exclude_unset,
            )

        if isinstance(value, dict):
            return dict(value)

        raise TypeError("Expected Pydantic model or dictionary")

    def _strip_response_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove MongoDB/API-only fields before validating with CompanySettings model.
        """
        cleaned = deepcopy(data)

        for key in ["_id", "id"]:
            cleaned.pop(key, None)

        return cleaned

    def _deep_merge(
        self,
        base: Dict[str, Any],
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Deep merge dictionaries.

        Used for PATCH operations so partial nested updates are validated
        against the complete final settings object.
        """
        merged = deepcopy(base)

        for key, value in updates.items():
            if (
                isinstance(value, dict)
                and isinstance(merged.get(key), dict)
            ):
                merged[key] = self._deep_merge(merged[key], value)
            else:
                merged[key] = value

        return merged

    def _validate_full_settings(
        self,
        settings_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Validate complete company settings using the model.

        This catches cross-field rules like:
        - working_days and weekend_days cannot overlap
        - PF rates must be 0 if PF is disabled
        - professional_tax_state required when professional tax is enabled
        - auto approval threshold cannot exceed manager approval threshold
        """
        try:
            payload = self._strip_response_fields(settings_data)
            validated = CompanySettings(**payload)
            return validated.model_dump()

        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=exc.errors(),
            )

        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

    async def _get_active_or_404(
        self,
        company_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Get active settings or raise 404.
        """
        company_id = self._normalize_company_id(company_id)

        settings = await self.repository.find_by_company_id(company_id)

        if not settings:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Active company settings not found for company_id: {company_id}",
            )

        return settings

    async def _get_any_or_404(
        self,
        company_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Get settings regardless of active status or raise 404.
        """
        company_id = self._normalize_company_id(company_id)

        settings = await self.repository.find_any_by_company_id(company_id)

        if not settings:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Company settings not found for company_id: {company_id}",
            )

        return settings

    async def _get_by_id_or_404(
        self,
        settings_id: str,
    ) -> Dict[str, Any]:
        """
        Get settings by ID or raise 404.
        """
        settings = await self.repository.find_by_id(settings_id)

        if not settings:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Company settings with ID '{settings_id}' not found",
            )

        return settings

    def _to_settings_response(
        self,
        settings: Dict[str, Any],
    ) -> CompanySettingsResponse:
        """
        Convert dict to full settings response.
        """
        return CompanySettingsResponse.model_validate(settings)

    def _validate_section_name(self, section_name: str) -> str:
        """
        Validate dynamic section name.
        """
        section_name = str(section_name).strip().lower()

        if section_name not in self.VALID_SECTION_NAMES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Invalid section_name. Must be one of: "
                    f"{', '.join(sorted(self.VALID_SECTION_NAMES))}"
                ),
            )

        return section_name

    def _validate_section_payload(
        self,
        section_name: str,
        section_data: Dict[str, Any],
        is_patch: bool = False,
    ) -> Dict[str, Any]:
        """
        Validate one section using the correct schema.

        For full section updates, strict full schemas are used.
        For patch updates, patch schemas are used.
        """
        section_name = self._validate_section_name(section_name)

        full_schema_map = {
            "company_info": CompanyInfoSchema,
            "system": SystemConfigSchema,
            "work_week": WorkWeekConfigSchema,
            "leave_policy": LeavePolicyConfigSchema,
            "payroll": PayrollConfigSchema,
            "claim_policy": ClaimPolicyConfigSchema,
        }

        patch_schema_map = {
            "company_info": PatchCompanyInfoRequest,
            "system": PatchSystemConfigRequest,
            "work_week": PatchWorkWeekRequest,
            "leave_policy": PatchLeavePolicyRequest,
            "payroll": PatchPayrollRequest,
            "claim_policy": PatchClaimPolicyRequest,
        }

        schema_cls = patch_schema_map[section_name] if is_patch else full_schema_map[section_name]

        try:
            validated = schema_cls(**section_data)
            return validated.model_dump(exclude_none=is_patch, exclude_unset=is_patch)

        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=exc.errors(),
            )

    async def _return_updated_settings(
        self,
        company_id: str,
        message: str,
        include_inactive: bool = False,
    ) -> CompanySettingsUpdatedResponse:
        """
        Fetch latest settings and return standard update response.
        """
        company_id = self._normalize_company_id(company_id)

        if include_inactive:
            settings = await self.repository.find_any_by_company_id(company_id)
        else:
            settings = await self.repository.find_by_company_id(company_id)

        if not settings:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Settings updated but failed to retrieve",
            )

        return CompanySettingsUpdatedResponse(
            message=message,
            settings=self._to_settings_response(settings),
        )

    # -------------------------
    # Create / Initialize
    # -------------------------

    async def create_settings(
        self,
        request: CreateCompanySettingsRequest,
        created_by: Optional[str] = None,
    ) -> CompanySettingsCreatedResponse:
        """
        Create new company settings.

        Usually called once during initial setup.
        """
        company_id = self._normalize_company_id(request.company_id)

        if await self.repository.exists_by_company_id(company_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Company settings already exist for company_id: {company_id}",
            )

        settings_data = request.model_dump()
        settings_data["company_id"] = company_id
        settings_data["created_by"] = created_by
        settings_data["updated_by"] = created_by

        validated_data = self._validate_full_settings(settings_data)

        try:
            settings_id = await self.repository.create(validated_data)

        except DuplicateKeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Company settings already exist for company_id: {company_id}",
            )

        settings = await self._get_by_id_or_404(settings_id)

        return CompanySettingsCreatedResponse(
            message="Company settings created successfully",
            settings_id=settings_id,
            settings=self._to_settings_response(settings),
        )

    async def initialize_default_settings(
        self,
        request: InitializeCompanySettingsRequest,
        created_by: Optional[str] = None,
    ) -> CompanySettingsInitializedResponse:
        """
        Initialize company settings with minimal required information.

        All other sections use model defaults.
        """
        company_id = self._normalize_company_id(request.company_id)

        if await self.repository.exists_by_company_id(company_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Company settings already exist for company_id: {company_id}",
            )

        settings_data = {
            "company_id": company_id,
            "company_info": {
                "company_name": request.company_name,
                "email": request.email,
                "address_line1": request.address_line1,
                "city": request.city,
                "state": request.state,
                "pincode": request.pincode,
                "country": request.country,
            },
            "created_by": created_by,
            "updated_by": created_by,
        }

        validated_data = self._validate_full_settings(settings_data)

        try:
            settings_id = await self.repository.create(validated_data)

        except DuplicateKeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Company settings already exist for company_id: {company_id}",
            )

        settings = await self._get_by_id_or_404(settings_id)

        return CompanySettingsInitializedResponse(
            message="Company settings initialized successfully",
            settings_id=settings_id,
            settings=self._to_settings_response(settings),
        )

    async def get_or_create_default_settings(
        self,
        request: CreateCompanySettingsRequest,
        created_by: Optional[str] = None,
    ) -> CompanySettingsResponse:
        """
        Get active default settings if present, otherwise create and return.

        Useful during first-time setup.
        """
        company_id = self._normalize_company_id(request.company_id)

        existing = await self.repository.find_by_company_id(company_id)

        if existing:
            return self._to_settings_response(existing)

        settings_data = request.model_dump()
        settings_data["company_id"] = company_id
        settings_data["created_by"] = created_by
        settings_data["updated_by"] = created_by

        validated_data = self._validate_full_settings(settings_data)

        try:
            result = await self.repository.get_or_create_default_settings(
                validated_data
            )
            return self._to_settings_response(result)

        except DuplicateKeyError:
            existing_after_race = await self.repository.find_by_company_id(company_id)

            if existing_after_race:
                return self._to_settings_response(existing_after_race)

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Company settings already exist for company_id: {company_id}",
            )

    # -------------------------
    # Read operations
    # -------------------------

    async def get_settings(
        self,
        company_id: str = "default",
        include_inactive: bool = False,
    ) -> CompanySettingsResponse:
        """
        Get company settings.

        By default, only active settings are returned.
        """
        company_id = self._normalize_company_id(company_id)

        if include_inactive:
            settings = await self._get_any_or_404(company_id)
        else:
            settings = await self._get_active_or_404(company_id)

        return self._to_settings_response(settings)

    async def get_settings_by_id(
        self,
        settings_id: str,
    ) -> CompanySettingsResponse:
        """
        Get company settings by MongoDB ID.
        """
        settings = await self._get_by_id_or_404(settings_id)
        return self._to_settings_response(settings)

    async def get_active_settings(self) -> CompanySettingsResponse:
        """
        Get active default company settings.

        Most commonly used by other HR services.
        """
        settings = await self._get_active_or_404("default")
        return self._to_settings_response(settings)

    async def get_summary(
        self,
        company_id: str = "default",
    ) -> CompanySettingsSummaryResponse:
        """
        Get lightweight settings summary.
        """
        company_id = self._normalize_company_id(company_id)

        summary = await self.repository.get_summary(company_id)

        if not summary:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Company settings summary not found for company_id: {company_id}",
            )

        return CompanySettingsSummaryResponse.model_validate(summary)

    async def has_settings_configured(
        self,
        company_id: str = "default",
    ) -> bool:
        """
        Check if company has active configured settings.
        """
        company_id = self._normalize_company_id(company_id)
        return await self.repository.has_settings_configured(company_id)

    async def get_settings_status(
        self,
        company_id: str = "default",
    ) -> CompanySettingsExistsResponse:
        """
        Return existence and active status for company settings.
        """
        company_id = self._normalize_company_id(company_id)

        settings = await self.repository.find_any_by_company_id(company_id)

        if not settings:
            return CompanySettingsExistsResponse(
                company_id=company_id,
                exists=False,
                is_active=False,
            )

        return CompanySettingsExistsResponse(
            company_id=company_id,
            exists=True,
            is_active=bool(settings.get("is_active", False)),
        )

    # -------------------------
    # Get specific sections
    # -------------------------

    async def get_section(
        self,
        section_name: str,
        company_id: str = "default",
    ) -> CompanySettingsSectionResponse:
        """
        Get one company settings section dynamically.
        """
        company_id = self._normalize_company_id(company_id)
        section_name = self._validate_section_name(section_name)

        section_data = await self.repository.get_section(
            section_name=section_name,
            company_id=company_id,
        )

        if section_data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Section '{section_name}' not found for company_id: "
                    f"{company_id}"
                ),
            )

        return CompanySettingsSectionResponse(
            company_id=company_id,
            section_name=section_name,
            section_data=section_data,
        )

    async def get_company_info(
        self,
        company_id: str = "default",
    ) -> CompanySettingsSectionResponse:
        return await self.get_section("company_info", company_id)

    async def get_system_config(
        self,
        company_id: str = "default",
    ) -> CompanySettingsSectionResponse:
        return await self.get_section("system", company_id)

    async def get_work_week(
        self,
        company_id: str = "default",
    ) -> CompanySettingsSectionResponse:
        return await self.get_section("work_week", company_id)

    async def get_leave_policy(
        self,
        company_id: str = "default",
    ) -> CompanySettingsSectionResponse:
        return await self.get_section("leave_policy", company_id)

    async def get_payroll(
        self,
        company_id: str = "default",
    ) -> CompanySettingsSectionResponse:
        return await self.get_section("payroll", company_id)

    async def get_claim_policy(
        self,
        company_id: str = "default",
    ) -> CompanySettingsSectionResponse:
        return await self.get_section("claim_policy", company_id)

    # -------------------------
    # Update full settings / patch settings
    # -------------------------

    async def update_settings(
        self,
        company_id: str,
        request: UpdateCompanySettingsRequest,
        updated_by: Optional[str] = None,
    ) -> CompanySettingsUpdatedResponse:
        """
        Update selected full sections of company settings.

        Each provided section replaces the existing section.
        """
        company_id = self._normalize_company_id(company_id)
        existing = await self._get_any_or_404(company_id)

        update_data = request.model_dump(exclude_unset=True)

        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields provided for update",
            )

        update_data["updated_by"] = updated_by

        validation_payload = self._strip_response_fields(existing)
        validation_payload.update(update_data)

        self._validate_full_settings(validation_payload)

        success = await self.repository.update_by_company_id(
            company_id=company_id,
            update_data=update_data,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update settings for company_id: {company_id}",
            )

        include_inactive = update_data.get("is_active") is False

        return await self._return_updated_settings(
            company_id=company_id,
            message="Company settings updated successfully",
            include_inactive=include_inactive,
        )

    async def patch_settings(
        self,
        company_id: str,
        request: PatchCompanySettingsRequest,
        updated_by: Optional[str] = None,
    ) -> CompanySettingsUpdatedResponse:
        """
        Partially update company settings using nested patch data.

        Example:
            {"work_week": {"working_hours_per_day": 7.5}}
        """
        company_id = self._normalize_company_id(company_id)
        existing = await self._get_active_or_404(company_id)

        patch_data = request.model_dump(
            exclude_unset=True,
            exclude_none=True,
        )

        if not patch_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields provided for patch",
            )

        validation_payload = self._deep_merge(
            self._strip_response_fields(existing),
            patch_data,
        )

        self._validate_full_settings(validation_payload)

        patch_data["updated_by"] = updated_by

        success = await self.repository.patch_by_company_id(
            company_id=company_id,
            update_data=patch_data,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to patch settings for company_id: {company_id}",
            )

        return await self._return_updated_settings(
            company_id=company_id,
            message="Company settings patched successfully",
        )

    # -------------------------
    # Update / patch specific sections
    # -------------------------

    async def update_section(
        self,
        company_id: str,
        section_name: str,
        section_data: Dict[str, Any],
        updated_by: Optional[str] = None,
    ) -> CompanySettingsUpdatedResponse:
        """
        Replace one full settings section.
        """
        company_id = self._normalize_company_id(company_id)
        section_name = self._validate_section_name(section_name)

        existing = await self._get_active_or_404(company_id)

        validated_section = self._validate_section_payload(
            section_name=section_name,
            section_data=section_data,
            is_patch=False,
        )

        validation_payload = self._strip_response_fields(existing)
        validation_payload[section_name] = validated_section

        self._validate_full_settings(validation_payload)

        success = await self.repository.update_section(
            section_name=section_name,
            section_data=validated_section,
            company_id=company_id,
            updated_by=updated_by,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update section '{section_name}'",
            )

        return await self._return_updated_settings(
            company_id=company_id,
            message=f"{section_name} updated successfully",
        )

    async def patch_section(
        self,
        company_id: str,
        section_name: str,
        section_data: Dict[str, Any],
        updated_by: Optional[str] = None,
    ) -> CompanySettingsUpdatedResponse:
        """
        Partially patch one settings section.
        """
        company_id = self._normalize_company_id(company_id)
        section_name = self._validate_section_name(section_name)

        existing = await self._get_active_or_404(company_id)

        validated_patch = self._validate_section_payload(
            section_name=section_name,
            section_data=section_data,
            is_patch=True,
        )

        existing_section = existing.get(section_name, {})

        merged_section = self._deep_merge(
            existing_section,
            validated_patch,
        )

        validation_payload = self._strip_response_fields(existing)
        validation_payload[section_name] = merged_section

        self._validate_full_settings(validation_payload)

        success = await self.repository.patch_section(
            section_name=section_name,
            section_data=validated_patch,
            company_id=company_id,
            updated_by=updated_by,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to patch section '{section_name}'",
            )

        return await self._return_updated_settings(
            company_id=company_id,
            message=f"{section_name} patched successfully",
        )

    async def update_company_info(
        self,
        company_id: str,
        request: UpdateCompanyInfoRequest,
        updated_by: Optional[str] = None,
    ) -> CompanySettingsUpdatedResponse:
        return await self.update_section(
            company_id=company_id,
            section_name="company_info",
            section_data=request.model_dump(),
            updated_by=updated_by,
        )

    async def update_system_config(
        self,
        company_id: str,
        request: UpdateSystemConfigRequest,
        updated_by: Optional[str] = None,
    ) -> CompanySettingsUpdatedResponse:
        return await self.update_section(
            company_id=company_id,
            section_name="system",
            section_data=request.model_dump(),
            updated_by=updated_by,
        )

    async def update_work_week(
        self,
        company_id: str,
        request: UpdateWorkWeekRequest,
        updated_by: Optional[str] = None,
    ) -> CompanySettingsUpdatedResponse:
        return await self.update_section(
            company_id=company_id,
            section_name="work_week",
            section_data=request.model_dump(),
            updated_by=updated_by,
        )

    async def update_leave_policy(
        self,
        company_id: str,
        request: UpdateLeavePolicyRequest,
        updated_by: Optional[str] = None,
    ) -> CompanySettingsUpdatedResponse:
        return await self.update_section(
            company_id=company_id,
            section_name="leave_policy",
            section_data=request.model_dump(),
            updated_by=updated_by,
        )

    async def update_payroll(
        self,
        company_id: str,
        request: UpdatePayrollRequest,
        updated_by: Optional[str] = None,
    ) -> CompanySettingsUpdatedResponse:
        return await self.update_section(
            company_id=company_id,
            section_name="payroll",
            section_data=request.model_dump(),
            updated_by=updated_by,
        )

    async def update_claim_policy(
        self,
        company_id: str,
        request: UpdateClaimPolicyRequest,
        updated_by: Optional[str] = None,
    ) -> CompanySettingsUpdatedResponse:
        return await self.update_section(
            company_id=company_id,
            section_name="claim_policy",
            section_data=request.model_dump(),
            updated_by=updated_by,
        )

    async def patch_company_info(
        self,
        company_id: str,
        request: PatchCompanyInfoRequest,
        updated_by: Optional[str] = None,
    ) -> CompanySettingsUpdatedResponse:
        return await self.patch_section(
            company_id=company_id,
            section_name="company_info",
            section_data=request.model_dump(exclude_unset=True, exclude_none=True),
            updated_by=updated_by,
        )

    async def patch_system_config(
        self,
        company_id: str,
        request: PatchSystemConfigRequest,
        updated_by: Optional[str] = None,
    ) -> CompanySettingsUpdatedResponse:
        return await self.patch_section(
            company_id=company_id,
            section_name="system",
            section_data=request.model_dump(exclude_unset=True, exclude_none=True),
            updated_by=updated_by,
        )

    async def patch_work_week(
        self,
        company_id: str,
        request: PatchWorkWeekRequest,
        updated_by: Optional[str] = None,
    ) -> CompanySettingsUpdatedResponse:
        return await self.patch_section(
            company_id=company_id,
            section_name="work_week",
            section_data=request.model_dump(exclude_unset=True, exclude_none=True),
            updated_by=updated_by,
        )

    async def patch_leave_policy(
        self,
        company_id: str,
        request: PatchLeavePolicyRequest,
        updated_by: Optional[str] = None,
    ) -> CompanySettingsUpdatedResponse:
        return await self.patch_section(
            company_id=company_id,
            section_name="leave_policy",
            section_data=request.model_dump(exclude_unset=True, exclude_none=True),
            updated_by=updated_by,
        )

    async def patch_payroll(
        self,
        company_id: str,
        request: PatchPayrollRequest,
        updated_by: Optional[str] = None,
    ) -> CompanySettingsUpdatedResponse:
        return await self.patch_section(
            company_id=company_id,
            section_name="payroll",
            section_data=request.model_dump(exclude_unset=True, exclude_none=True),
            updated_by=updated_by,
        )

    async def patch_claim_policy(
        self,
        company_id: str,
        request: PatchClaimPolicyRequest,
        updated_by: Optional[str] = None,
    ) -> CompanySettingsUpdatedResponse:
        return await self.patch_section(
            company_id=company_id,
            section_name="claim_policy",
            section_data=request.model_dump(exclude_unset=True, exclude_none=True),
            updated_by=updated_by,
        )

    # -------------------------
    # Activate / Deactivate
    # -------------------------

    async def deactivate_settings(
        self,
        company_id: str,
        updated_by: Optional[str] = None,
    ) -> CompanySettingsStatusResponse:
        """
        Deactivate company settings.

        Warning:
        Deactivating company settings can affect HR operations.
        In production, routes should restrict this to Admin only.
        """
        company_id = self._normalize_company_id(company_id)
        settings = await self._get_any_or_404(company_id)

        if not settings.get("is_active", False):
            return CompanySettingsStatusResponse(
                message="Company settings are already inactive",
                company_id=company_id,
                is_active=False,
            )

        success = await self.repository.deactivate_by_company_id(
            company_id=company_id,
            updated_by=updated_by,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to deactivate settings for company_id: {company_id}",
            )

        return CompanySettingsStatusResponse(
            message="Company settings deactivated successfully",
            company_id=company_id,
            is_active=False,
        )

    async def activate_settings(
        self,
        company_id: str,
        updated_by: Optional[str] = None,
    ) -> CompanySettingsStatusResponse:
        """
        Reactivate company settings.
        """
        company_id = self._normalize_company_id(company_id)
        settings = await self._get_any_or_404(company_id)

        if settings.get("is_active", False):
            return CompanySettingsStatusResponse(
                message="Company settings are already active",
                company_id=company_id,
                is_active=True,
            )

        validation_payload = self._strip_response_fields(settings)
        validation_payload["is_active"] = True
        validation_payload["updated_by"] = updated_by

        self._validate_full_settings(validation_payload)

        success = await self.repository.activate_by_company_id(
            company_id=company_id,
            updated_by=updated_by,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to activate settings for company_id: {company_id}",
            )

        return CompanySettingsStatusResponse(
            message="Company settings activated successfully",
            company_id=company_id,
            is_active=True,
        )

    # -------------------------
    # Validation helper
    # -------------------------

    async def validate_settings_payload(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Validate a raw company settings payload.

        Useful for future admin preview/validation endpoints.
        """
        try:
            self._validate_full_settings(payload)

            return {
                "is_valid": True,
                "errors": [],
            }

        except HTTPException as exc:
            errors = exc.detail if isinstance(exc.detail, list) else [{"error": exc.detail}]

            return {
                "is_valid": False,
                "errors": errors,
            }