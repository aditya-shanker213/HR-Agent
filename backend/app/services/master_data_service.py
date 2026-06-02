"""
Master Data Service - Business logic for master data management.

Current scope:
- Departments
- Designations
- Leave Types
- Claim Types
- Holidays

Future scope:
- Company Settings

Pattern:
Route → Service → Repository → MongoDB

Responsibilities of this service:
- Apply business rules
- Validate references before database write
- Add audit fields like created_by and updated_by
- Keep routes thin
- Keep repositories focused only on MongoDB queries

Important:
- Routes should handle HTTP request/response and role dependencies.
- Services should handle business rules.
- Repositories should handle MongoDB operations.
"""

from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from pymongo.errors import DuplicateKeyError

from backend.app.models.claim_type_model import ClaimType
from backend.app.models.holiday_model import Holiday
from backend.app.models.leave_type_model import LeaveType
from backend.app.repositories.claim_type_repository import ClaimTypeRepository
from backend.app.repositories.department_repository import DepartmentRepository
from backend.app.repositories.designation_repository import DesignationRepository
from backend.app.repositories.holiday_repository import HolidayRepository
from backend.app.repositories.leave_type_repository import LeaveTypeRepository
from backend.app.repositories.user_repository import UserRepository


class MasterDataService:
    """
    Service layer for master data operations.

    This service currently handles:
    - Department master data
    - Designation master data
    - Leave type master data
    - Claim type master data
    - Holiday master data

    Later:
    - EmployeeRepository should replace UserRepository for department head validation
    """

    def __init__(
        self,
        department_repo: DepartmentRepository,
        user_repo: UserRepository,
        designation_repo: Optional[DesignationRepository] = None,
        leave_type_repo: Optional[LeaveTypeRepository] = None,
        claim_type_repo: Optional[ClaimTypeRepository] = None,
        holiday_repo: Optional[HolidayRepository] = None,
    ):
        self.department_repo = department_repo
        self.user_repo = user_repo
        self.designation_repo = designation_repo
        self.leave_type_repo = leave_type_repo
        self.claim_type_repo = claim_type_repo
        self.holiday_repo = holiday_repo

    # -------------------------
    # Internal helper methods
    # -------------------------

    def _clean_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove keys where value is None.

        Useful for update requests because update schemas have all fields optional.
        Only fields actually provided should be updated.
        """
        return {key: value for key, value in data.items() if value is not None}

    def _require_designation_repo(self) -> DesignationRepository:
        """
        Ensure designation repository is available before using designation methods.
        """
        if self.designation_repo is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Designation repository is not configured",
            )

        return self.designation_repo

    def _require_leave_type_repo(self) -> LeaveTypeRepository:
        """
        Ensure leave type repository is available before using leave type methods.
        """
        if self.leave_type_repo is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Leave type repository is not configured",
            )

        return self.leave_type_repo

    def _require_claim_type_repo(self) -> ClaimTypeRepository:
        """
        Ensure claim type repository is available before using claim type methods.
        """
        if self.claim_type_repo is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Claim type repository is not configured",
            )

        return self.claim_type_repo


    def _require_holiday_repo(self) -> HolidayRepository:
        """
        Ensure holiday repository is available before using holiday methods.
        """
        if self.holiday_repo is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Holiday repository is not configured",
            )

        return self.holiday_repo

    def _validate_leave_type_payload(self, data: Dict[str, Any]) -> None:
        """
        Validate complete leave type business rules using LeaveType model.

        For update operations, service first merges existing data with update data,
        then validates the merged payload so partial updates cannot create invalid rules.
        """
        try:
            LeaveType(**data)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

    def _validate_claim_type_payload(self, data: Dict[str, Any]) -> None:
        """
        Validate complete claim type business rules using ClaimType model.

        For update operations, service first merges existing data with update data,
        then validates the merged payload so partial updates cannot create invalid rules.
        """
        try:
            ClaimType(**data)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )


    def _validate_holiday_payload(self, data: Dict[str, Any]) -> None:
        """
        Validate complete holiday business rules using Holiday model.

        For update operations, service first merges existing data with update data,
        then validates the merged payload so partial updates cannot create invalid rules.
        """
        try:
            Holiday(**data)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

    async def _validate_head_user(self, head_id: Optional[str]) -> None:
        """
        Validate department head.

        Current temporary logic:
        - head_id is checked against users collection.

        Later production logic:
        - Replace this with employee_repo.find_by_id(head_id)
        - Because department head should be an employee profile, not just auth user.
        """
        if not head_id:
            return

        head_user = await self.user_repo.find_by_id(head_id)

        if not head_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Head user with ID '{head_id}' not found",
            )

        if not head_user.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Head user account is not active",
            )

    async def _validate_parent_department(
        self,
        parent_id: Optional[str],
        current_department_id: Optional[str] = None,
    ) -> None:
        """
        Validate parent department.

        Rules:
        - Parent department must exist.
        - Parent department must be active.
        - A department cannot be its own parent.
        """
        if not parent_id:
            return

        if current_department_id and parent_id == current_department_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Department cannot be its own parent",
            )

        parent_exists = await self.department_repo.active_exists_by_id(parent_id)

        if not parent_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Parent department '{parent_id}' not found or inactive",
            )

        # Future improvement:
        # Add circular hierarchy validation.

    async def _validate_designation_department(
        self,
        department_id: Optional[str],
    ) -> None:
        """
        Validate department_id for designation.

        Rules:
        - department_id is optional.
        - If provided, department must exist and be active.
        """
        if not department_id:
            return

        department_exists = await self.department_repo.active_exists_by_id(department_id)

        if not department_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Department '{department_id}' not found or inactive",
            )

    async def _enrich_department_details(
        self,
        department: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Add extra calculated fields for department detail response.

        Adds:
        - head_name
        - head_email
        - parent_name
        - employee_count
        - children_count

        employee_count is currently 0 because employee module is not created yet.
        """
        enriched = dict(department)

        head_id = enriched.get("head_id")
        if head_id:
            head_user = await self.user_repo.find_by_id(head_id)

            if head_user:
                enriched["head_name"] = head_user.get("username")
                enriched["head_email"] = head_user.get("email")
            else:
                enriched["head_name"] = None
                enriched["head_email"] = None
        else:
            enriched["head_name"] = None
            enriched["head_email"] = None

        parent_id = enriched.get("parent_id")
        if parent_id:
            parent_department = await self.department_repo.find_by_id(parent_id)
            enriched["parent_name"] = (
                parent_department.get("name") if parent_department else None
            )
        else:
            enriched["parent_name"] = None

        enriched["children_count"] = await self.department_repo.get_children_count(
            enriched.get("id") or enriched.get("_id")
        )

        # TODO: Replace with employee_repo.count_by_department() after employee module.
        enriched["employee_count"] = 0

        return enriched

    async def _enrich_designation_details(
        self,
        designation: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Add extra calculated fields for designation detail response.

        Adds:
        - department_name
        - department_code
        - employee_count

        employee_count is currently 0 because employee module is not created yet.
        """
        enriched = dict(designation)

        department_id = enriched.get("department_id")
        if department_id:
            department = await self.department_repo.find_by_id(department_id)

            if department:
                enriched["department_name"] = department.get("name")
                enriched["department_code"] = department.get("code")
            else:
                enriched["department_name"] = None
                enriched["department_code"] = None
        else:
            enriched["department_name"] = None
            enriched["department_code"] = None

        # TODO: Replace with employee_repo.count_by_designation() after employee module.
        enriched["employee_count"] = 0

        return enriched

    # -------------------------
    # Department Operations
    # -------------------------

    async def create_department(
        self,
        department_data: Dict[str, Any],
        created_by: str,
    ) -> Dict[str, Any]:
        """
        Create a new department.
        """
        department_data = self._clean_payload(department_data)

        code = department_data.get("code")
        if not code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Department code is required",
            )

        if await self.department_repo.code_exists(code):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Department code '{code}' already exists",
            )

        await self._validate_head_user(department_data.get("head_id"))
        await self._validate_parent_department(department_data.get("parent_id"))

        department_data["created_by"] = created_by
        department_data["updated_by"] = created_by

        try:
            department_id = await self.department_repo.create(department_data)

        except DuplicateKeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Department code '{code}' already exists",
            )

        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create department",
            )

        department = await self.department_repo.find_by_id(department_id)

        if not department:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Department created but failed to retrieve",
            )

        return department

    async def get_department_by_id(
        self,
        department_id: str,
        include_details: bool = False,
    ) -> Dict[str, Any]:
        """
        Get department by ID.
        """
        department = await self.department_repo.find_by_id(department_id)

        if not department:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Department with ID '{department_id}' not found",
            )

        if include_details:
            department = await self._enrich_department_details(department)

        return department

    async def list_departments(
        self,
        is_active: Optional[bool] = None,
        location: Optional[str] = None,
        parent_id: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "display_order",
        sort_order: str = "asc",
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        List departments with filtering, search, sorting, and pagination.
        """
        departments = await self.department_repo.list_all(
            is_active=is_active,
            location=location,
            parent_id=parent_id,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            skip=skip,
            limit=limit,
        )

        total_count = await self.department_repo.count(
            is_active=is_active,
            location=location,
            parent_id=parent_id,
            search=search,
        )

        return departments, total_count

    async def update_department(
        self,
        department_id: str,
        update_data: Dict[str, Any],
        updated_by: str,
    ) -> Dict[str, Any]:
        """
        Update department fields.
        """
        update_data = self._clean_payload(update_data)

        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields provided for update",
            )

        existing_department = await self.department_repo.find_by_id(department_id)

        if not existing_department:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Department with ID '{department_id}' not found",
            )

        new_code = update_data.get("code")
        existing_code = existing_department.get("code")

        if new_code and new_code != existing_code:
            if await self.department_repo.code_exists(
                code=new_code,
                exclude_id=department_id,
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Department code '{new_code}' already exists",
                )

        if "head_id" in update_data:
            await self._validate_head_user(update_data.get("head_id"))

        if "parent_id" in update_data:
            await self._validate_parent_department(
                parent_id=update_data.get("parent_id"),
                current_department_id=department_id,
            )

        update_data["updated_by"] = updated_by

        try:
            updated = await self.department_repo.update(
                department_id=department_id,
                update_data=update_data,
            )

        except DuplicateKeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Department code '{new_code}' already exists",
            )

        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update department",
            )

        if not updated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update department",
            )

        department = await self.department_repo.find_by_id(department_id)

        if not department:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Department updated but failed to retrieve",
            )

        return department

    async def deactivate_department(
        self,
        department_id: str,
        updated_by: str,
    ) -> bool:
        """
        Deactivate a department using soft delete.
        """
        department = await self.department_repo.find_by_id(department_id)

        if not department:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Department with ID '{department_id}' not found",
            )

        if not department.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Department is already inactive",
            )

        if await self.department_repo.has_active_children(department_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate department with active child departments",
            )

        # TODO:
        # After employee module is created:
        # Do not allow deactivation if active employees belong to this department.

        deactivated = await self.department_repo.deactivate(
            department_id=department_id,
            updated_by=updated_by,
        )

        if not deactivated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to deactivate department",
            )

        return True

    async def activate_department(
        self,
        department_id: str,
        updated_by: str,
    ) -> Dict[str, Any]:
        """
        Reactivate an inactive department.
        """
        department = await self.department_repo.find_by_id(department_id)

        if not department:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Department with ID '{department_id}' not found",
            )

        if department.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Department is already active",
            )

        parent_id = department.get("parent_id")
        if parent_id:
            parent_active = await self.department_repo.active_exists_by_id(parent_id)

            if not parent_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot activate department because parent department is inactive",
                )

        activated = await self.department_repo.activate(
            department_id=department_id,
            updated_by=updated_by,
        )

        if not activated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to activate department",
            )

        activated_department = await self.department_repo.find_by_id(department_id)

        if not activated_department:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Department activated but failed to retrieve",
            )

        return activated_department

    async def bulk_import_departments(
        self,
        departments: List[Dict[str, Any]],
        created_by: str,
        skip_duplicates: bool = True,
    ) -> Dict[str, Any]:
        """
        Bulk import departments.
        """
        if not departments:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Departments list cannot be empty",
            )

        prepared_departments: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        seen_codes: set[str] = set()

        for index, raw_department in enumerate(departments):
            try:
                department_data = self._clean_payload(dict(raw_department))

                code = department_data.get("code")
                if not code:
                    failed.append(
                        {
                            "index": index,
                            "code": None,
                            "error": "Department code is required",
                        }
                    )
                    continue

                normalized_code = code.strip().upper()

                if normalized_code in seen_codes:
                    duplicate_error = {
                        "index": index,
                        "code": normalized_code,
                        "error": "Duplicate department code inside import payload",
                    }

                    if skip_duplicates:
                        skipped.append(duplicate_error)
                        continue

                    failed.append(duplicate_error)
                    continue

                if await self.department_repo.code_exists(normalized_code):
                    duplicate_error = {
                        "index": index,
                        "code": normalized_code,
                        "error": "Department code already exists",
                    }

                    if skip_duplicates:
                        skipped.append(duplicate_error)
                        continue

                    failed.append(duplicate_error)
                    continue

                await self._validate_head_user(department_data.get("head_id"))
                await self._validate_parent_department(department_data.get("parent_id"))

                department_data["created_by"] = created_by
                department_data["updated_by"] = created_by

                prepared_departments.append(department_data)
                seen_codes.add(normalized_code)

            except HTTPException as exc:
                failed.append(
                    {
                        "index": index,
                        "code": raw_department.get("code"),
                        "error": exc.detail,
                    }
                )

            except Exception as exc:
                failed.append(
                    {
                        "index": index,
                        "code": raw_department.get("code"),
                        "error": str(exc),
                    }
                )

        created_ids, insert_errors = await self.department_repo.create_many(
            prepared_departments
        )

        failed.extend(insert_errors)

        return {
            "message": "Bulk department import completed",
            "created_count": len(created_ids),
            "skipped_count": len(skipped),
            "failed_count": len(failed),
            "created_ids": created_ids,
            "errors": skipped + failed,
        }

    async def get_department_statistics(self) -> Dict[str, Any]:
        """
        Get department statistics.
        """
        return await self.department_repo.get_statistics()

    # -------------------------
    # Designation Operations
    # -------------------------

    async def create_designation(
        self,
        designation_data: Dict[str, Any],
        created_by: str,
    ) -> Dict[str, Any]:
        """
        Create a new designation.
        """
        designation_repo = self._require_designation_repo()
        designation_data = self._clean_payload(designation_data)

        code = designation_data.get("code")
        if not code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Designation code is required",
            )

        if await designation_repo.code_exists(code):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Designation code '{code}' already exists",
            )

        await self._validate_designation_department(
            designation_data.get("department_id")
        )

        designation_data["created_by"] = created_by
        designation_data["updated_by"] = created_by

        try:
            designation_id = await designation_repo.create(designation_data)

        except DuplicateKeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Designation code '{code}' already exists",
            )

        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create designation",
            )

        designation = await designation_repo.find_by_id(designation_id)

        if not designation:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Designation created but failed to retrieve",
            )

        return designation

    async def get_designation_by_id(
        self,
        designation_id: str,
        include_details: bool = False,
    ) -> Dict[str, Any]:
        """
        Get designation by ID.
        """
        designation_repo = self._require_designation_repo()

        designation = await designation_repo.find_by_id(designation_id)

        if not designation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Designation with ID '{designation_id}' not found",
            )

        if include_details:
            designation = await self._enrich_designation_details(designation)

        return designation

    async def list_designations(
        self,
        is_active: Optional[bool] = None,
        department_id: Optional[str] = None,
        level: Optional[int] = None,
        search: Optional[str] = None,
        sort_by: str = "display_order",
        sort_order: str = "asc",
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        List designations with filtering, search, sorting, and pagination.
        """
        designation_repo = self._require_designation_repo()

        designations = await designation_repo.list_all(
            is_active=is_active,
            department_id=department_id,
            level=level,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            skip=skip,
            limit=limit,
        )

        total_count = await designation_repo.count(
            is_active=is_active,
            department_id=department_id,
            level=level,
            search=search,
        )

        return designations, total_count

    async def list_designations_for_dropdown(
        self,
        department_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List active designations for frontend dropdowns.
        """
        designation_repo = self._require_designation_repo()

        return await designation_repo.list_active_for_dropdown(
            department_id=department_id,
        )

    async def update_designation(
        self,
        designation_id: str,
        update_data: Dict[str, Any],
        updated_by: str,
    ) -> Dict[str, Any]:
        """
        Update designation fields.
        """
        designation_repo = self._require_designation_repo()
        update_data = self._clean_payload(update_data)

        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields provided for update",
            )

        existing_designation = await designation_repo.find_by_id(designation_id)

        if not existing_designation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Designation with ID '{designation_id}' not found",
            )

        new_code = update_data.get("code")
        existing_code = existing_designation.get("code")

        if new_code and new_code != existing_code:
            if await designation_repo.code_exists(
                code=new_code,
                exclude_id=designation_id,
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Designation code '{new_code}' already exists",
                )

        if "department_id" in update_data:
            await self._validate_designation_department(
                update_data.get("department_id")
            )

        update_data["updated_by"] = updated_by

        try:
            updated = await designation_repo.update(
                designation_id=designation_id,
                update_data=update_data,
            )

        except DuplicateKeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Designation code '{new_code}' already exists",
            )

        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update designation",
            )

        if not updated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update designation",
            )

        designation = await designation_repo.find_by_id(designation_id)

        if not designation:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Designation updated but failed to retrieve",
            )

        return designation

    async def deactivate_designation(
        self,
        designation_id: str,
        updated_by: str,
    ) -> bool:
        """
        Deactivate designation using soft delete.
        """
        designation_repo = self._require_designation_repo()

        designation = await designation_repo.find_by_id(designation_id)

        if not designation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Designation with ID '{designation_id}' not found",
            )

        if not designation.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Designation is already inactive",
            )

        # TODO:
        # After employee module is created:
        # Do not allow deactivation if active employees use this designation.

        deactivated = await designation_repo.deactivate(
            designation_id=designation_id,
            updated_by=updated_by,
        )

        if not deactivated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to deactivate designation",
            )

        return True

    async def activate_designation(
        self,
        designation_id: str,
        updated_by: str,
    ) -> Dict[str, Any]:
        """
        Reactivate an inactive designation.
        """
        designation_repo = self._require_designation_repo()

        designation = await designation_repo.find_by_id(designation_id)

        if not designation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Designation with ID '{designation_id}' not found",
            )

        if designation.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Designation is already active",
            )

        department_id = designation.get("department_id")
        if department_id:
            department_active = await self.department_repo.active_exists_by_id(
                department_id
            )

            if not department_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot activate designation because linked department is inactive",
                )

        activated = await designation_repo.activate(
            designation_id=designation_id,
            updated_by=updated_by,
        )

        if not activated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to activate designation",
            )

        activated_designation = await designation_repo.find_by_id(designation_id)

        if not activated_designation:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Designation activated but failed to retrieve",
            )

        return activated_designation

    async def bulk_import_designations(
        self,
        designations: List[Dict[str, Any]],
        created_by: str,
        skip_duplicates: bool = True,
    ) -> Dict[str, Any]:
        """
        Bulk import designations.
        """
        designation_repo = self._require_designation_repo()

        if not designations:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Designations list cannot be empty",
            )

        prepared_designations: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        seen_codes: set[str] = set()

        for index, raw_designation in enumerate(designations):
            try:
                designation_data = self._clean_payload(dict(raw_designation))

                code = designation_data.get("code")
                if not code:
                    failed.append(
                        {
                            "index": index,
                            "code": None,
                            "error": "Designation code is required",
                        }
                    )
                    continue

                normalized_code = code.strip().upper()

                if normalized_code in seen_codes:
                    duplicate_error = {
                        "index": index,
                        "code": normalized_code,
                        "error": "Duplicate designation code inside import payload",
                    }

                    if skip_duplicates:
                        skipped.append(duplicate_error)
                        continue

                    failed.append(duplicate_error)
                    continue

                if await designation_repo.code_exists(normalized_code):
                    duplicate_error = {
                        "index": index,
                        "code": normalized_code,
                        "error": "Designation code already exists",
                    }

                    if skip_duplicates:
                        skipped.append(duplicate_error)
                        continue

                    failed.append(duplicate_error)
                    continue

                await self._validate_designation_department(
                    designation_data.get("department_id")
                )

                designation_data["created_by"] = created_by
                designation_data["updated_by"] = created_by

                prepared_designations.append(designation_data)
                seen_codes.add(normalized_code)

            except HTTPException as exc:
                failed.append(
                    {
                        "index": index,
                        "code": raw_designation.get("code"),
                        "error": exc.detail,
                    }
                )

            except Exception as exc:
                failed.append(
                    {
                        "index": index,
                        "code": raw_designation.get("code"),
                        "error": str(exc),
                    }
                )

        created_ids, insert_errors = await designation_repo.create_many(
            prepared_designations
        )

        failed.extend(insert_errors)

        return {
            "message": "Bulk designation import completed",
            "created_count": len(created_ids),
            "skipped_count": len(skipped),
            "failed_count": len(failed),
            "created_ids": created_ids,
            "errors": skipped + failed,
        }

    async def get_designation_statistics(self) -> Dict[str, Any]:
        """
        Get designation statistics.
        """
        designation_repo = self._require_designation_repo()
        return await designation_repo.get_statistics()

    # -------------------------
    # Leave Type Operations
    # -------------------------

    async def create_leave_type(
        self,
        leave_type_data: Dict[str, Any],
        created_by: str,
    ) -> Dict[str, Any]:
        """
        Create a new leave type.
        """
        leave_type_repo = self._require_leave_type_repo()
        leave_type_data = self._clean_payload(leave_type_data)

        code = leave_type_data.get("code")
        if not code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Leave type code is required",
            )

        if await leave_type_repo.code_exists(code):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Leave type code '{code}' already exists",
            )

        leave_type_data["created_by"] = created_by
        leave_type_data["updated_by"] = created_by

        self._validate_leave_type_payload(leave_type_data)

        try:
            leave_type_id = await leave_type_repo.create(leave_type_data)

        except DuplicateKeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Leave type code '{code}' already exists",
            )

        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create leave type",
            )

        leave_type = await leave_type_repo.find_by_id(leave_type_id)

        if not leave_type:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Leave type created but failed to retrieve",
            )

        return leave_type

    async def get_leave_type_by_id(
        self,
        leave_type_id: str,
        include_details: bool = False,
    ) -> Dict[str, Any]:
        """
        Get leave type by ID.
        """
        leave_type_repo = self._require_leave_type_repo()

        leave_type = await leave_type_repo.find_by_id(leave_type_id)

        if not leave_type:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Leave type with ID '{leave_type_id}' not found",
            )

        if include_details:
            leave_type = dict(leave_type)
            # TODO: Replace these values with real aggregation after leave module.
            leave_type.setdefault("total_employees_granted", 0)
            leave_type.setdefault("total_applications_this_year", 0)

        return leave_type

    async def list_leave_types(
        self,
        is_active: Optional[bool] = None,
        is_paid: Optional[bool] = None,
        requires_approval: Optional[bool] = None,
        requires_documentation: Optional[bool] = None,
        carry_forward_allowed: Optional[bool] = None,
        encashment_allowed: Optional[bool] = None,
        is_accrued: Optional[bool] = None,
        available_during_probation: Optional[bool] = None,
        gender_specific: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "display_order",
        sort_order: str = "asc",
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        List leave types with filtering, search, sorting, and pagination.
        """
        leave_type_repo = self._require_leave_type_repo()

        leave_types = await leave_type_repo.list_all(
            is_active=is_active,
            is_paid=is_paid,
            requires_approval=requires_approval,
            requires_documentation=requires_documentation,
            carry_forward_allowed=carry_forward_allowed,
            encashment_allowed=encashment_allowed,
            is_accrued=is_accrued,
            available_during_probation=available_during_probation,
            gender_specific=gender_specific,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            skip=skip,
            limit=limit,
        )

        total_count = await leave_type_repo.count(
            is_active=is_active,
            is_paid=is_paid,
            requires_approval=requires_approval,
            requires_documentation=requires_documentation,
            carry_forward_allowed=carry_forward_allowed,
            encashment_allowed=encashment_allowed,
            is_accrued=is_accrued,
            available_during_probation=available_during_probation,
            gender_specific=gender_specific,
            search=search,
        )

        return leave_types, total_count

    async def list_leave_types_for_dropdown(
        self,
        gender: Optional[str] = None,
        include_unpaid: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        List active leave types for frontend dropdowns.
        """
        leave_type_repo = self._require_leave_type_repo()

        return await leave_type_repo.list_active_for_dropdown(
            gender=gender,
            include_unpaid=include_unpaid,
        )

    async def update_leave_type(
        self,
        leave_type_id: str,
        update_data: Dict[str, Any],
        updated_by: str,
    ) -> Dict[str, Any]:
        """
        Update leave type fields.

        Partial update safety:
        - Fetch existing document
        - Merge existing + update data
        - Validate complete merged payload using LeaveType model
        - Save only requested update fields
        """
        leave_type_repo = self._require_leave_type_repo()
        update_data = self._clean_payload(update_data)

        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields provided for update",
            )

        existing_leave_type = await leave_type_repo.find_by_id(leave_type_id)

        if not existing_leave_type:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Leave type with ID '{leave_type_id}' not found",
            )

        new_code = update_data.get("code")
        existing_code = existing_leave_type.get("code")

        if new_code and new_code != existing_code:
            if await leave_type_repo.code_exists(
                code=new_code,
                exclude_id=leave_type_id,
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Leave type code '{new_code}' already exists",
                )

        update_data["updated_by"] = updated_by

        validation_payload = {
            key: value
            for key, value in existing_leave_type.items()
            if key not in {"_id", "id", "created_at", "updated_at"}
        }
        validation_payload.update(update_data)

        self._validate_leave_type_payload(validation_payload)

        try:
            updated = await leave_type_repo.update(
                leave_type_id=leave_type_id,
                update_data=update_data,
            )

        except DuplicateKeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Leave type code '{new_code}' already exists",
            )

        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update leave type",
            )

        if not updated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update leave type",
            )

        leave_type = await leave_type_repo.find_by_id(leave_type_id)

        if not leave_type:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Leave type updated but failed to retrieve",
            )

        return leave_type

    async def deactivate_leave_type(
        self,
        leave_type_id: str,
        updated_by: str,
    ) -> bool:
        """
        Deactivate a leave type using soft delete.
        """
        leave_type_repo = self._require_leave_type_repo()

        leave_type = await leave_type_repo.find_by_id(leave_type_id)

        if not leave_type:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Leave type with ID '{leave_type_id}' not found",
            )

        if not leave_type.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Leave type is already inactive",
            )

        # TODO:
        # After employee/leave module is created:
        # Do not allow deactivation if active balances or pending leaves use this leave type.

        deactivated = await leave_type_repo.deactivate(
            leave_type_id=leave_type_id,
            updated_by=updated_by,
        )

        if not deactivated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to deactivate leave type",
            )

        return True

    async def activate_leave_type(
        self,
        leave_type_id: str,
        updated_by: str,
    ) -> Dict[str, Any]:
        """
        Reactivate an inactive leave type.
        """
        leave_type_repo = self._require_leave_type_repo()

        leave_type = await leave_type_repo.find_by_id(leave_type_id)

        if not leave_type:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Leave type with ID '{leave_type_id}' not found",
            )

        if leave_type.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Leave type is already active",
            )

        validation_payload = {
            key: value
            for key, value in leave_type.items()
            if key not in {"_id", "id", "created_at", "updated_at"}
        }
        validation_payload["is_active"] = True
        validation_payload["updated_by"] = updated_by

        self._validate_leave_type_payload(validation_payload)

        activated = await leave_type_repo.activate(
            leave_type_id=leave_type_id,
            updated_by=updated_by,
        )

        if not activated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to activate leave type",
            )

        activated_leave_type = await leave_type_repo.find_by_id(leave_type_id)

        if not activated_leave_type:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Leave type activated but failed to retrieve",
            )

        return activated_leave_type

    async def bulk_import_leave_types(
        self,
        leave_types: List[Dict[str, Any]],
        created_by: str,
        skip_duplicates: bool = True,
    ) -> Dict[str, Any]:
        """
        Bulk import leave types.
        """
        leave_type_repo = self._require_leave_type_repo()

        if not leave_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Leave types list cannot be empty",
            )

        prepared_leave_types: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        seen_codes: set[str] = set()

        for index, raw_leave_type in enumerate(leave_types):
            try:
                leave_type_data = self._clean_payload(dict(raw_leave_type))

                code = leave_type_data.get("code")
                if not code:
                    failed.append(
                        {
                            "index": index,
                            "code": None,
                            "error": "Leave type code is required",
                        }
                    )
                    continue

                normalized_code = code.strip().upper()

                if normalized_code in seen_codes:
                    duplicate_error = {
                        "index": index,
                        "code": normalized_code,
                        "error": "Duplicate leave type code inside import payload",
                    }

                    if skip_duplicates:
                        skipped.append(duplicate_error)
                        continue

                    failed.append(duplicate_error)
                    continue

                if await leave_type_repo.code_exists(normalized_code):
                    duplicate_error = {
                        "index": index,
                        "code": normalized_code,
                        "error": "Leave type code already exists",
                    }

                    if skip_duplicates:
                        skipped.append(duplicate_error)
                        continue

                    failed.append(duplicate_error)
                    continue

                leave_type_data["created_by"] = created_by
                leave_type_data["updated_by"] = created_by

                self._validate_leave_type_payload(leave_type_data)

                prepared_leave_types.append(leave_type_data)
                seen_codes.add(normalized_code)

            except HTTPException as exc:
                failed.append(
                    {
                        "index": index,
                        "code": raw_leave_type.get("code"),
                        "error": exc.detail,
                    }
                )

            except Exception as exc:
                failed.append(
                    {
                        "index": index,
                        "code": raw_leave_type.get("code"),
                        "error": str(exc),
                    }
                )

        created_ids, insert_errors = await leave_type_repo.create_many(
            prepared_leave_types
        )

        failed.extend(insert_errors)

        return {
            "message": "Bulk leave type import completed",
            "created_count": len(created_ids),
            "skipped_count": len(skipped),
            "failed_count": len(failed),
            "created_ids": created_ids,
            "errors": skipped + failed,
        }

    async def get_leave_type_statistics(self) -> Dict[str, Any]:
        """
        Get leave type statistics.
        """
        leave_type_repo = self._require_leave_type_repo()
        return await leave_type_repo.get_statistics()

    async def get_leave_type_rules_by_id(
        self,
        leave_type_id: str,
    ) -> Dict[str, Any]:
        """
        Get active leave type rules by ID.

        This will be used later by leave application validation.
        """
        leave_type_repo = self._require_leave_type_repo()

        rules = await leave_type_repo.get_leave_rules_by_id(leave_type_id)

        if not rules:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Active leave type rules for ID '{leave_type_id}' not found",
            )

        return rules

    # -------------------------
    # Claim Type Operations
    # -------------------------

    async def create_claim_type(
        self,
        claim_type_data: Dict[str, Any],
        created_by: str,
    ) -> Dict[str, Any]:
        """
        Create a new claim type.
        """
        claim_type_repo = self._require_claim_type_repo()
        claim_type_data = self._clean_payload(claim_type_data)

        code = claim_type_data.get("code")
        if not code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Claim type code is required",
            )

        if await claim_type_repo.code_exists(code):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Claim type code '{code}' already exists",
            )

        claim_type_data["created_by"] = created_by
        claim_type_data["updated_by"] = created_by

        self._validate_claim_type_payload(claim_type_data)

        try:
            claim_type_id = await claim_type_repo.create(claim_type_data)

        except DuplicateKeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Claim type code '{code}' already exists",
            )

        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create claim type",
            )

        claim_type = await claim_type_repo.find_by_id(claim_type_id)

        if not claim_type:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Claim type created but failed to retrieve",
            )

        return claim_type

    async def get_claim_type_by_id(
        self,
        claim_type_id: str,
        include_details: bool = False,
    ) -> Dict[str, Any]:
        """
        Get claim type by ID.
        """
        claim_type_repo = self._require_claim_type_repo()

        claim_type = await claim_type_repo.find_by_id(claim_type_id)

        if not claim_type:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Claim type with ID '{claim_type_id}' not found",
            )

        if include_details:
            claim_type = dict(claim_type)
            # TODO: Replace these values with real aggregation after claim module.
            claim_type.setdefault("total_employees_using", 0)
            claim_type.setdefault("total_claims_this_year", 0)
            claim_type.setdefault("total_amount_claimed", 0)
            claim_type.setdefault("total_amount_approved", 0)
            claim_type.setdefault("average_claim_amount", 0.0)

        return claim_type

    async def list_claim_types(
        self,
        is_active: Optional[bool] = None,
        requires_bill: Optional[bool] = None,
        requires_approval: Optional[bool] = None,
        is_taxable: Optional[bool] = None,
        currency: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "display_order",
        sort_order: str = "asc",
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        List claim types with filtering, search, sorting, and pagination.
        """
        claim_type_repo = self._require_claim_type_repo()

        claim_types = await claim_type_repo.list_all(
            is_active=is_active,
            requires_bill=requires_bill,
            requires_approval=requires_approval,
            is_taxable=is_taxable,
            currency=currency,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            skip=skip,
            limit=limit,
        )

        total_count = await claim_type_repo.count(
            is_active=is_active,
            requires_bill=requires_bill,
            requires_approval=requires_approval,
            is_taxable=is_taxable,
            currency=currency,
            search=search,
        )

        return claim_types, total_count

    async def list_claim_types_for_dropdown(
        self,
        include_taxable: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        List active claim types for frontend dropdowns.
        """
        claim_type_repo = self._require_claim_type_repo()

        return await claim_type_repo.list_active_for_dropdown(
            include_taxable=include_taxable,
        )

    async def update_claim_type(
        self,
        claim_type_id: str,
        update_data: Dict[str, Any],
        updated_by: str,
    ) -> Dict[str, Any]:
        """
        Update claim type fields.

        Partial update safety:
        - Fetch existing document
        - Merge existing + update data
        - Validate complete merged payload using ClaimType model
        - Save only requested update fields
        """
        claim_type_repo = self._require_claim_type_repo()
        update_data = self._clean_payload(update_data)

        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields provided for update",
            )

        existing_claim_type = await claim_type_repo.find_by_id(claim_type_id)

        if not existing_claim_type:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Claim type with ID '{claim_type_id}' not found",
            )

        new_code = update_data.get("code")
        existing_code = existing_claim_type.get("code")

        if new_code and new_code != existing_code:
            if await claim_type_repo.code_exists(
                code=new_code,
                exclude_id=claim_type_id,
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Claim type code '{new_code}' already exists",
                )

        update_data["updated_by"] = updated_by

        validation_payload = {
            key: value
            for key, value in existing_claim_type.items()
            if key not in {"_id", "id", "created_at", "updated_at"}
        }
        validation_payload.update(update_data)

        self._validate_claim_type_payload(validation_payload)

        try:
            updated = await claim_type_repo.update(
                claim_type_id=claim_type_id,
                update_data=update_data,
            )

        except DuplicateKeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Claim type code '{new_code}' already exists",
            )

        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update claim type",
            )

        if not updated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update claim type",
            )

        claim_type = await claim_type_repo.find_by_id(claim_type_id)

        if not claim_type:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Claim type updated but failed to retrieve",
            )

        return claim_type

    async def deactivate_claim_type(
        self,
        claim_type_id: str,
        updated_by: str,
    ) -> bool:
        """
        Deactivate a claim type using soft delete.
        """
        claim_type_repo = self._require_claim_type_repo()

        claim_type = await claim_type_repo.find_by_id(claim_type_id)

        if not claim_type:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Claim type with ID '{claim_type_id}' not found",
            )

        if not claim_type.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Claim type is already inactive",
            )

        # TODO:
        # After claim module is created:
        # Do not allow deactivation if pending/active claims use this claim type.

        deactivated = await claim_type_repo.deactivate(
            claim_type_id=claim_type_id,
            updated_by=updated_by,
        )

        if not deactivated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to deactivate claim type",
            )

        return True

    async def activate_claim_type(
        self,
        claim_type_id: str,
        updated_by: str,
    ) -> Dict[str, Any]:
        """
        Reactivate an inactive claim type.
        """
        claim_type_repo = self._require_claim_type_repo()

        claim_type = await claim_type_repo.find_by_id(claim_type_id)

        if not claim_type:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Claim type with ID '{claim_type_id}' not found",
            )

        if claim_type.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Claim type is already active",
            )

        validation_payload = {
            key: value
            for key, value in claim_type.items()
            if key not in {"_id", "id", "created_at", "updated_at"}
        }
        validation_payload["is_active"] = True
        validation_payload["updated_by"] = updated_by

        self._validate_claim_type_payload(validation_payload)

        activated = await claim_type_repo.activate(
            claim_type_id=claim_type_id,
            updated_by=updated_by,
        )

        if not activated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to activate claim type",
            )

        activated_claim_type = await claim_type_repo.find_by_id(claim_type_id)

        if not activated_claim_type:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Claim type activated but failed to retrieve",
            )

        return activated_claim_type

    async def bulk_import_claim_types(
        self,
        claim_types: List[Dict[str, Any]],
        created_by: str,
        skip_duplicates: bool = True,
    ) -> Dict[str, Any]:
        """
        Bulk import claim types.
        """
        claim_type_repo = self._require_claim_type_repo()

        if not claim_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Claim types list cannot be empty",
            )

        prepared_claim_types: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        seen_codes: set[str] = set()

        for index, raw_claim_type in enumerate(claim_types):
            try:
                claim_type_data = self._clean_payload(dict(raw_claim_type))

                code = claim_type_data.get("code")
                if not code:
                    failed.append(
                        {
                            "index": index,
                            "code": None,
                            "error": "Claim type code is required",
                        }
                    )
                    continue

                normalized_code = code.strip().upper()

                if normalized_code in seen_codes:
                    duplicate_error = {
                        "index": index,
                        "code": normalized_code,
                        "error": "Duplicate claim type code inside import payload",
                    }

                    if skip_duplicates:
                        skipped.append(duplicate_error)
                        continue

                    failed.append(duplicate_error)
                    continue

                if await claim_type_repo.code_exists(normalized_code):
                    duplicate_error = {
                        "index": index,
                        "code": normalized_code,
                        "error": "Claim type code already exists",
                    }

                    if skip_duplicates:
                        skipped.append(duplicate_error)
                        continue

                    failed.append(duplicate_error)
                    continue

                claim_type_data["created_by"] = created_by
                claim_type_data["updated_by"] = created_by

                self._validate_claim_type_payload(claim_type_data)

                prepared_claim_types.append(claim_type_data)
                seen_codes.add(normalized_code)

            except HTTPException as exc:
                failed.append(
                    {
                        "index": index,
                        "code": raw_claim_type.get("code"),
                        "error": exc.detail,
                    }
                )

            except Exception as exc:
                failed.append(
                    {
                        "index": index,
                        "code": raw_claim_type.get("code"),
                        "error": str(exc),
                    }
                )

        created_ids, insert_errors = await claim_type_repo.create_many(
            prepared_claim_types
        )

        failed.extend(insert_errors)

        return {
            "message": "Bulk claim type import completed",
            "created_count": len(created_ids),
            "skipped_count": len(skipped),
            "failed_count": len(failed),
            "created_ids": created_ids,
            "errors": skipped + failed,
        }

    async def bulk_update_claim_type_limits(
        self,
        updates: List[Dict[str, Any]],
        updated_by: str,
    ) -> Dict[str, Any]:
        """
        Bulk update claim type limits.

        Expected item format:
        {
            "id": "claim_type_id",
            "default_annual_limit": 5000,
            "default_monthly_limit": 1000,
            "max_claim_amount": 2000
        }
        """
        claim_type_repo = self._require_claim_type_repo()

        if not updates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Updates list cannot be empty",
            )

        updated_count, errors = await claim_type_repo.bulk_update_limits(
            updates=updates,
            updated_by=updated_by,
        )

        return {
            "message": "Bulk claim type limit update completed",
            "updated_count": updated_count,
            "failed_count": len(errors),
            "errors": errors,
        }

    async def get_claim_type_statistics(self) -> Dict[str, Any]:
        """
        Get claim type statistics.
        """
        claim_type_repo = self._require_claim_type_repo()
        return await claim_type_repo.get_statistics()

    async def get_claim_type_rules_by_id(
        self,
        claim_type_id: str,
    ) -> Dict[str, Any]:
        """
        Get active claim type rules by ID.

        This will be used later by claim submission validation.
        """
        claim_type_repo = self._require_claim_type_repo()

        rules = await claim_type_repo.get_claim_rules_by_id(claim_type_id)

        if not rules:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Active claim type rules for ID '{claim_type_id}' not found",
            )

        return rules

    # -------------------------
    # Holiday Operations
    # -------------------------

    async def create_holiday(
        self,
        holiday_data: Dict[str, Any],
        created_by: str,
    ) -> Dict[str, Any]:
        """
        Create a new holiday.
        """
        holiday_repo = self._require_holiday_repo()
        holiday_data = self._clean_payload(holiday_data)

        holiday_date = holiday_data.get("date")
        holiday_name = holiday_data.get("name")

        if not holiday_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Holiday date is required",
            )

        if not holiday_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Holiday name is required",
            )

        holiday_data["created_by"] = created_by
        holiday_data["updated_by"] = created_by

        self._validate_holiday_payload(holiday_data)

        if await holiday_repo.duplicate_exists(
            holiday_date=holiday_date,
            name=holiday_name,
            location=holiday_data.get("location"),
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Holiday already exists for this date, name, and location",
            )

        try:
            holiday_id = await holiday_repo.create(holiday_data)

        except DuplicateKeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Holiday already exists",
            )

        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create holiday",
            )

        holiday = await holiday_repo.find_by_id(holiday_id)

        if not holiday:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Holiday created but failed to retrieve",
            )

        return holiday

    async def get_holiday_by_id(
        self,
        holiday_id: str,
    ) -> Dict[str, Any]:
        """
        Get holiday by ID.
        """
        holiday_repo = self._require_holiday_repo()

        holiday = await holiday_repo.find_by_id(holiday_id)

        if not holiday:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Holiday with ID '{holiday_id}' not found",
            )

        return holiday

    async def list_holidays(
        self,
        year: Optional[int] = None,
        month: Optional[int] = None,
        holiday_type: Optional[str] = None,
        location: Optional[str] = None,
        is_optional: Optional[bool] = None,
        is_working_day: Optional[bool] = None,
        is_half_day: Optional[bool] = None,
        is_active: Optional[bool] = None,
        from_date: Optional[Any] = None,
        to_date: Optional[Any] = None,
        search: Optional[str] = None,
        sort_by: str = "date",
        sort_order: str = "asc",
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        List holidays with filtering, search, sorting, and pagination.
        """
        holiday_repo = self._require_holiday_repo()

        holidays = await holiday_repo.list_all(
            year=year,
            month=month,
            holiday_type=holiday_type,
            location=location,
            is_optional=is_optional,
            is_working_day=is_working_day,
            is_half_day=is_half_day,
            is_active=is_active,
            from_date=from_date,
            to_date=to_date,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            skip=skip,
            limit=limit,
        )

        total_count = await holiday_repo.count(
            year=year,
            month=month,
            holiday_type=holiday_type,
            location=location,
            is_optional=is_optional,
            is_working_day=is_working_day,
            is_half_day=is_half_day,
            is_active=is_active,
            from_date=from_date,
            to_date=to_date,
            search=search,
        )

        return holidays, total_count

    async def list_holidays_for_calendar(
        self,
        year: int,
        month: Optional[int] = None,
        location: Optional[str] = None,
        include_optional: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        List active holidays for frontend calendar.
        """
        holiday_repo = self._require_holiday_repo()

        return await holiday_repo.list_for_calendar(
            year=year,
            month=month,
            location=location,
            include_optional=include_optional,
        )

    async def list_upcoming_holidays(
        self,
        days: int = 30,
        location: Optional[str] = None,
        include_optional: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        List upcoming holidays for employee dashboard.
        """
        holiday_repo = self._require_holiday_repo()

        return await holiday_repo.list_upcoming_holidays(
            days=days,
            location=location,
            include_optional=include_optional,
        )

    async def update_holiday(
        self,
        holiday_id: str,
        update_data: Dict[str, Any],
        updated_by: str,
    ) -> Dict[str, Any]:
        """
        Update holiday fields.

        Partial update safety:
        - Fetch existing document
        - Merge existing + update data
        - Validate complete merged payload using Holiday model
        - Save only requested update fields
        """
        holiday_repo = self._require_holiday_repo()
        update_data = self._clean_payload(update_data)

        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields provided for update",
            )

        existing_holiday = await holiday_repo.find_by_id(holiday_id)

        if not existing_holiday:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Holiday with ID '{holiday_id}' not found",
            )

        validation_payload = {
            key: value
            for key, value in existing_holiday.items()
            if key not in {"_id", "id", "created_at", "updated_at"}
        }
        validation_payload.update(update_data)
        validation_payload["updated_by"] = updated_by

        self._validate_holiday_payload(validation_payload)

        check_date = validation_payload.get("date")
        check_name = validation_payload.get("name")
        check_location = validation_payload.get("location")

        if check_date and check_name:
            if await holiday_repo.duplicate_exists(
                holiday_date=check_date,
                name=check_name,
                location=check_location,
                exclude_id=holiday_id,
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Holiday already exists for this date, name, and location",
                )

        update_data["updated_by"] = updated_by

        try:
            updated = await holiday_repo.update(
                holiday_id=holiday_id,
                update_data=update_data,
            )

        except DuplicateKeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Holiday already exists",
            )

        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update holiday",
            )

        if not updated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update holiday",
            )

        holiday = await holiday_repo.find_by_id(holiday_id)

        if not holiday:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Holiday updated but failed to retrieve",
            )

        return holiday

    async def deactivate_holiday(
        self,
        holiday_id: str,
        updated_by: str,
    ) -> bool:
        """
        Deactivate a holiday using soft delete.
        """
        holiday_repo = self._require_holiday_repo()

        holiday = await holiday_repo.find_by_id(holiday_id)

        if not holiday:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Holiday with ID '{holiday_id}' not found",
            )

        if not holiday.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Holiday is already inactive",
            )

        deactivated = await holiday_repo.deactivate(
            holiday_id=holiday_id,
            updated_by=updated_by,
        )

        if not deactivated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to deactivate holiday",
            )

        return True

    async def activate_holiday(
        self,
        holiday_id: str,
        updated_by: str,
    ) -> Dict[str, Any]:
        """
        Reactivate an inactive holiday.
        """
        holiday_repo = self._require_holiday_repo()

        holiday = await holiday_repo.find_by_id(holiday_id)

        if not holiday:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Holiday with ID '{holiday_id}' not found",
            )

        if holiday.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Holiday is already active",
            )

        validation_payload = {
            key: value
            for key, value in holiday.items()
            if key not in {"_id", "id", "created_at", "updated_at"}
        }
        validation_payload["is_active"] = True
        validation_payload["updated_by"] = updated_by

        self._validate_holiday_payload(validation_payload)

        activated = await holiday_repo.activate(
            holiday_id=holiday_id,
            updated_by=updated_by,
        )

        if not activated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to activate holiday",
            )

        activated_holiday = await holiday_repo.find_by_id(holiday_id)

        if not activated_holiday:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Holiday activated but failed to retrieve",
            )

        return activated_holiday

    async def bulk_import_holidays(
        self,
        holidays: List[Dict[str, Any]],
        created_by: str,
        skip_duplicates: bool = True,
    ) -> Dict[str, Any]:
        """
        Bulk import holidays.
        """
        holiday_repo = self._require_holiday_repo()

        if not holidays:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Holidays list cannot be empty",
            )

        prepared_holidays: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        seen_keys: set[tuple[str, str, str]] = set()

        for index, raw_holiday in enumerate(holidays):
            try:
                holiday_data = self._clean_payload(dict(raw_holiday))

                holiday_date = holiday_data.get("date")
                holiday_name = holiday_data.get("name")
                location = holiday_data.get("location")

                if not holiday_date:
                    failed.append(
                        {
                            "index": index,
                            "date": None,
                            "name": holiday_name,
                            "error": "Holiday date is required",
                        }
                    )
                    continue

                if not holiday_name:
                    failed.append(
                        {
                            "index": index,
                            "date": str(holiday_date),
                            "name": None,
                            "error": "Holiday name is required",
                        }
                    )
                    continue

                holiday_data["created_by"] = created_by
                holiday_data["updated_by"] = created_by

                self._validate_holiday_payload(holiday_data)

                normalized_key = (
                    str(holiday_date),
                    str(holiday_name).strip().lower(),
                    str(location or "all").strip().lower(),
                )

                if normalized_key in seen_keys:
                    duplicate_error = {
                        "index": index,
                        "date": str(holiday_date),
                        "name": holiday_name,
                        "error": "Duplicate holiday inside import payload",
                    }

                    if skip_duplicates:
                        skipped.append(duplicate_error)
                        continue

                    failed.append(duplicate_error)
                    continue

                if await holiday_repo.duplicate_exists(
                    holiday_date=holiday_date,
                    name=holiday_name,
                    location=location,
                ):
                    duplicate_error = {
                        "index": index,
                        "date": str(holiday_date),
                        "name": holiday_name,
                        "error": "Holiday already exists",
                    }

                    if skip_duplicates:
                        skipped.append(duplicate_error)
                        continue

                    failed.append(duplicate_error)
                    continue

                prepared_holidays.append(holiday_data)
                seen_keys.add(normalized_key)

            except HTTPException as exc:
                failed.append(
                    {
                        "index": index,
                        "date": str(raw_holiday.get("date")),
                        "name": raw_holiday.get("name"),
                        "error": exc.detail,
                    }
                )

            except Exception as exc:
                failed.append(
                    {
                        "index": index,
                        "date": str(raw_holiday.get("date")),
                        "name": raw_holiday.get("name"),
                        "error": str(exc),
                    }
                )

        created_ids, insert_errors = await holiday_repo.create_many(prepared_holidays)

        failed.extend(insert_errors)

        return {
            "message": "Bulk holiday import completed",
            "created_count": len(created_ids),
            "skipped_count": len(skipped),
            "failed_count": len(failed),
            "created_ids": created_ids,
            "errors": skipped + failed,
        }

    async def get_holiday_statistics(
        self,
        year: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get holiday statistics.
        """
        holiday_repo = self._require_holiday_repo()
        return await holiday_repo.get_statistics(year=year)

    async def calculate_leave_days_using_holidays(
        self,
        from_date: Any,
        to_date: Any,
        location: Optional[str] = None,
        exclude_weekends: bool = True,
        include_optional_holidays: bool = False,
    ) -> Dict[str, Any]:
        """
        Calculate leave days using holiday calendar.

        This helper will be useful later in Leave Management.
        """
        holiday_repo = self._require_holiday_repo()

        return await holiday_repo.calculate_leave_days(
            from_date=from_date,
            to_date=to_date,
            location=location,
            exclude_weekends=exclude_weekends,
            include_optional_holidays=include_optional_holidays,
        )

