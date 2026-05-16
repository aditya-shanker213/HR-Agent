"""
Master Data Service - Business logic for master data management.

Current scope:
- Departments
- Designations

Future scope:
- Leave Types
- Claim Types
- Company Settings
- Holiday Calendar

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

from backend.app.repositories.department_repository import DepartmentRepository
from backend.app.repositories.designation_repository import DesignationRepository
from backend.app.repositories.user_repository import UserRepository


class MasterDataService:
    """
    Service layer for master data operations.

    This service currently handles:
    - Department master data
    - Designation master data

    Later:
    - LeaveTypeRepository can be added here
    - ClaimTypeRepository can be added here
    - EmployeeRepository should replace UserRepository for department head validation
    """

    def __init__(
        self,
        department_repo: DepartmentRepository,
        user_repo: UserRepository,
        designation_repo: Optional[DesignationRepository] = None,
    ):
        self.department_repo = department_repo
        self.user_repo = user_repo
        self.designation_repo = designation_repo

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

        Business rules:
        - Designation code must be unique.
        - department_id is optional.
        - If department_id is provided, department must exist and be active.
        - created_by and updated_by are set from current logged-in user.
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
        include_global: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        List active designations for frontend dropdowns.
        """
        designation_repo = self._require_designation_repo()

        return await designation_repo.list_active_for_dropdown(
            department_id=department_id,
            include_global=include_global,
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
        Deactivate a designation using soft delete.
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
            await self._validate_designation_department(department_id)

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