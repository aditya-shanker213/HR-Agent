"""
Leave service - Business logic for leave management.

Pattern:
Route → Service → Repository → MongoDB

This service handles:
- Leave request creation with validation
- Leave balance checking
- Working day calculation
- Approval workflow management
- Leave status transitions
- Holiday and weekend detection
- Conflict detection
- Backdated leave validation
- Emergency leave rules
- HRMS/read-only protection

Important:
- Service validates business rules.
- Repository handles database operations.
- Routes handle HTTP and auth only.
- Model handles data validation.

Production/MVP note:
- In MVP/local mode, MongoDB acts as mock HRMS.
- In production HRMS read-only mode, write operations should be disabled
  or routed to approved HRMS/company workflow APIs.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from backend.app.models.leave_model import (
    LeaveApprovalStatus,
    LeaveApproverRole,
    LeaveAttachment,
    LeaveBalanceAction,
    LeaveDay,
    LeaveDayType,
    LeavePolicySnapshot,
    LeaveRejectionReason,
    LeaveRequest,
    LeaveSource,
    LeaveStatus,
)
from backend.app.repositories.employee_repository import EmployeeRepository
from backend.app.repositories.holiday_repository import HolidayRepository
from backend.app.repositories.leave_repository import LeaveRepository
from backend.app.repositories.leave_type_repository import LeaveTypeRepository

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.app.services.conflict_service import ConflictService


class LeaveService:
    """
    Service layer for leave management.
    """

    FINAL_STATUSES = {
        LeaveStatus.APPROVED.value,
        LeaveStatus.REJECTED.value,
        LeaveStatus.CANCELLED.value,
        LeaveStatus.WITHDRAWN.value,
    }

    EDITABLE_STATUSES = {
        LeaveStatus.DRAFT.value,
        LeaveStatus.PENDING.value,
    }

    APPROVAL_STATUSES = {
        LeaveStatus.PENDING.value,
        LeaveStatus.MANAGER_APPROVED.value,
    }

    def __init__(
        self,
        leave_repo: LeaveRepository,
        employee_repo: EmployeeRepository,
        leave_type_repo: LeaveTypeRepository,
        holiday_repo: HolidayRepository,
        conflict_service: Optional["ConflictService"] = None,
        mode: str = "local_mvp",
    ):
        self.leave_repo = leave_repo
        self.employee_repo = employee_repo
        self.leave_type_repo = leave_type_repo
        self.holiday_repo = holiday_repo
        self.conflict_service = conflict_service
        self.mode = mode

    # -------------------------
    # Mode helpers
    # -------------------------

    def _is_hrms_readonly_mode(self) -> bool:
        """
        Check whether leave write operations should be blocked.

        Supported modes:
        - local_mvp
        - hrms_readonly
        - hrms_write_approved
        """
        return self.mode == "hrms_readonly"

    def _ensure_write_allowed(self) -> None:
        """
        Block local write operations in HRMS read-only mode.
        """
        if self._is_hrms_readonly_mode():
            raise ValueError(
                "Leave write operation is disabled in HRMS read-only mode. "
                "Use approved HRMS workflow integration instead."
            )

    def _ensure_record_is_writable(self, leave: Dict[str, Any]) -> None:
        """
        Block updates to HRMS read-only records.
        """
        if leave.get("is_read_only") is True or leave.get("source") == LeaveSource.HRMS.value:
            raise ValueError("This leave record is read-only because it comes from HRMS")

    # -------------------------
    # Common helpers
    # -------------------------

    def _normalize_company_id(self, company_id: Optional[str] = "default") -> str:
        """
        Normalize company_id.
        """
        if not company_id:
            return "default"

        company_id = str(company_id).strip().lower()

        if not company_id:
            return "default"

        if not company_id.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                "company_id can contain only letters, numbers, hyphen, and underscore"
            )

        return company_id

    def _clean_text(self, value: Optional[str]) -> Optional[str]:
        """
        Clean optional text.
        """
        if value is None:
            return None

        value = str(value).strip()
        return value or None

    async def _get_employee_or_raise(
        self,
        employee_id: str,
        company_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Get employee or raise error.
        """
        employee = await self.employee_repo.find_by_id(employee_id, company_id)

        if not employee:
            raise ValueError(f"Employee {employee_id} not found")

        if not employee.get("is_active", False):
            raise ValueError(f"Employee {employee_id} is inactive")

        return employee

    async def _get_leave_type_or_raise(
        self,
        leave_type_id: str,
        company_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Get leave type or raise error.
        """
        leave_type = await self.leave_type_repo.find_by_id(leave_type_id, company_id)

        if not leave_type:
            raise ValueError(f"Leave type {leave_type_id} not found")

        if not leave_type.get("is_active", False):
            raise ValueError("Leave type is inactive")

        return leave_type

    def _get_employee_full_name(self, employee: Dict[str, Any]) -> str:
        """
        Build employee full name safely.
        """
        if employee.get("full_name"):
            return str(employee["full_name"]).strip()

        parts = [
            employee.get("first_name"),
            employee.get("middle_name"),
            employee.get("last_name"),
        ]

        full_name = " ".join(str(part).strip() for part in parts if part)

        return full_name or employee.get("employee_name") or employee.get("employee_code", "Employee")

    def _get_manager_name(self, employee: Dict[str, Any]) -> Optional[str]:
        """
        Get manager name from employee snapshot if available.
        """
        return (
            employee.get("manager_name")
            or employee.get("reporting_manager_name")
            or None
        )

    def _get_department_name(self, employee: Dict[str, Any]) -> Optional[str]:
        """
        Get department name from employee snapshot if available.
        """
        return employee.get("department_name")

    async def _get_leave_balance(
        self,
        employee: Dict[str, Any],
        leave_type_code: str,
        year: Optional[int] = None,
    ) -> float:
        """
        Get leave balance for employee and leave type.
        """
        if year is None:
            year = datetime.utcnow().year

        leave_type_code = str(leave_type_code).strip().upper()
        leave_balances = employee.get("leave_balances", [])

        for balance in leave_balances:
            if str(balance.get("leave_type_code", "")).strip().upper() == leave_type_code:
                balance_year = balance.get("year")
                if balance_year is None or int(balance_year) == int(year):
                    return float(balance.get("available", 0.0) or 0.0)

        return 0.0

    async def _update_leave_balance(
        self,
        employee_id: str,
        leave_type_code: str,
        amount: float,
        operation: str = "deduct",
        company_id: str = "default",
        year: Optional[int] = None,
    ) -> bool:
        """
        Update employee leave balance.

        operation:
        - deduct
        - restore
        """
        if year is None:
            year = datetime.utcnow().year

        employee = await self.employee_repo.find_by_id(employee_id, company_id)

        if not employee:
            return False

        leave_type_code = str(leave_type_code).strip().upper()
        leave_balances = employee.get("leave_balances", [])
        updated = False

        for balance in leave_balances:
            if str(balance.get("leave_type_code", "")).strip().upper() != leave_type_code:
                continue

            balance_year = balance.get("year")
            if balance_year is not None and int(balance_year) != int(year):
                continue

            used = float(balance.get("used", 0.0) or 0.0)
            available = float(balance.get("available", 0.0) or 0.0)

            if operation == "deduct":
                if available < amount:
                    raise ValueError(
                        f"Insufficient leave balance. Available: {available}, Required: {amount}"
                    )

                balance["used"] = used + amount
                balance["available"] = max(0.0, available - amount)

            elif operation == "restore":
                balance["used"] = max(0.0, used - amount)
                balance["available"] = available + amount

            else:
                raise ValueError("Invalid leave balance operation")

            balance["updated_at"] = datetime.utcnow()
            updated = True
            break

        if updated:
            await self.employee_repo.update(
                employee_id,
                {"leave_balances": leave_balances},
                company_id,
            )

        return updated

    async def _calculate_leave_days(
        self,
        start_date: date,
        end_date: date,
        half_day_dates: Optional[List[date]] = None,
        half_day_types: Optional[List[LeaveDayType]] = None,
        company_id: str = "default",
    ) -> Tuple[List[LeaveDay], float]:
        """
        Calculate leave days with holiday and weekend detection.

        Returns:
            (leave_days, total_days_to_deduct)
        """
        if end_date < start_date:
            raise ValueError("end_date cannot be before start_date")

        leave_days: List[LeaveDay] = []
        current_date = start_date
        total_deduction = 0.0

        holidays = await self.holiday_repo.list_by_date_range(
            start_date,
            end_date,
            company_id,
        )

        holiday_map: Dict[date, Dict[str, Any]] = {}

        for holiday in holidays:
            holiday_date = holiday.get("date")

            if isinstance(holiday_date, datetime):
                holiday_date = holiday_date.date()

            if holiday_date and not holiday.get("is_working_day", False):
                holiday_map[holiday_date] = holiday

        half_day_map: Dict[date, LeaveDayType] = {}

        if half_day_dates or half_day_types:
            if not half_day_dates or not half_day_types:
                raise ValueError("half_day_dates and half_day_types must be provided together")

            if len(half_day_dates) != len(half_day_types):
                raise ValueError("half_day_dates and half_day_types must have same length")

            if len(half_day_dates) != len(set(half_day_dates)):
                raise ValueError("half_day_dates cannot contain duplicate dates")

            half_day_map = dict(zip(half_day_dates, half_day_types))

        while current_date <= end_date:
            is_weekend = current_date.weekday() in [5, 6]
            holiday = holiday_map.get(current_date)
            is_holiday = holiday is not None
            holiday_name = holiday.get("name") if holiday else None

            day_type = half_day_map.get(current_date, LeaveDayType.FULL_DAY)

            if is_weekend or is_holiday:
                deduction = 0.0
            elif day_type == LeaveDayType.FULL_DAY:
                deduction = 1.0
            else:
                deduction = 0.5

            leave_day = LeaveDay(
                date=current_date,
                day_type=day_type,
                is_holiday=is_holiday,
                is_weekend=is_weekend,
                deduction=deduction,
                holiday_name=holiday_name,
            )

            leave_days.append(leave_day)
            total_deduction += deduction

            current_date += timedelta(days=1)

        return leave_days, total_deduction

    def _validate_leave_rules(
        self,
        leave_type: Dict[str, Any],
        total_days: float,
        start_date: date,
        is_emergency: bool = False,
        is_half_day: bool = False,
        employee: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Validate leave against leave type rules.
        """
        min_notice_days = int(leave_type.get("min_notice_days", 0) or 0)

        if min_notice_days > 0 and not is_emergency:
            days_until_leave = (start_date - date.today()).days

            if days_until_leave < min_notice_days:
                raise ValueError(
                    f"Leave requires {min_notice_days} days notice. "
                    f"You have only {days_until_leave} days."
                )

        max_consecutive = leave_type.get("max_consecutive_days")

        if max_consecutive is not None and total_days > float(max_consecutive):
            raise ValueError(
                f"Maximum consecutive days for {leave_type.get('name', 'this leave type')} "
                f"is {max_consecutive}. You requested {total_days} days."
            )

        if is_half_day and not leave_type.get("allow_half_day", True):
            raise ValueError(f"{leave_type.get('name', 'This leave type')} does not allow half-day leave")

        if employee and employee.get("employment_status") == "probation":
            if not leave_type.get("available_during_probation", True):
                raise ValueError(
                    f"{leave_type.get('name', 'This leave type')} is not available during probation"
                )

    def _build_policy_snapshot(self, leave_type: Dict[str, Any]) -> LeavePolicySnapshot:
        """
        Store important leave policy values at request time.
        """
        return LeavePolicySnapshot(
            leave_type_code=leave_type.get("code"),
            requires_approval=leave_type.get("requires_approval", True),
            requires_documentation=leave_type.get("requires_documentation", False),
            available_during_probation=leave_type.get("available_during_probation", True),
            max_consecutive_days=leave_type.get("max_consecutive_days"),
            min_notice_days=leave_type.get("min_notice_days"),
            allow_half_day=leave_type.get("allow_half_day", True),
            allow_backdated=leave_type.get("allow_backdated", False),
        )

    async def _find_hr_approver_id(
        self,
        company_id: str = "default",
    ) -> Optional[str]:
        """
        Try to find an HR/Admin employee for second-level approval.

        This depends on employee repository implementation.
        If unavailable, return None and service will continue without HR step.
        """
        if hasattr(self.employee_repo, "find_by_role"):
            try:
                hr_employee = await self.employee_repo.find_by_role("hr", company_id)
                if hr_employee:
                    return hr_employee.get("id") or hr_employee.get("_id")
            except Exception:
                return None

        return None

    async def _build_approval_chain(
        self,
        employee: Dict[str, Any],
        leave_type: Dict[str, Any],
        total_days: float,
        company_id: str = "default",
    ) -> Tuple[List[Dict[str, Any]], Optional[str], bool, LeaveStatus]:
        """
        Build approval chain for leave request.

        Returns:
            approval_chain, current_approver_id, requires_hr_approval, initial_status
        """
        approval_chain: List[Dict[str, Any]] = []
        requires_hr_approval = False

        if not leave_type.get("requires_approval", True):
            return approval_chain, None, False, LeaveStatus.APPROVED

        manager_id = employee.get("manager_id")
        manager_name = self._get_manager_name(employee) or "Manager"

        if manager_id:
            approval_chain.append(
                {
                    "step_order": 1,
                    "approver_id": manager_id,
                    "approver_name": manager_name,
                    "approver_role": LeaveApproverRole.MANAGER.value,
                    "status": LeaveApprovalStatus.PENDING.value,
                    "comments": None,
                    "rejection_reason": None,
                    "action_date": None,
                    "delegated_to_id": None,
                    "delegated_to_name": None,
                }
            )

        documentation_required = leave_type.get("requires_documentation", False)
        code = str(leave_type.get("code", "")).strip().upper()

        if (
            documentation_required
            or code in {"MEDICAL", "MATERNITY", "PATERNITY"}
            or total_days > 5
        ):
            requires_hr_approval = True

        if requires_hr_approval:
            hr_approver_id = await self._find_hr_approver_id(company_id)

            if hr_approver_id:
                approval_chain.append(
                    {
                        "step_order": 2,
                        "approver_id": hr_approver_id,
                        "approver_name": "HR",
                        "approver_role": LeaveApproverRole.HR.value,
                        "status": LeaveApprovalStatus.PENDING.value,
                        "comments": None,
                        "rejection_reason": None,
                        "action_date": None,
                        "delegated_to_id": None,
                        "delegated_to_name": None,
                    }
                )

        if approval_chain:
            return approval_chain, approval_chain[0]["approver_id"], requires_hr_approval, LeaveStatus.PENDING

        return approval_chain, None, requires_hr_approval, LeaveStatus.APPROVED

    async def _check_leave_conflicts(
        self,
        employee_id: str,
        start_date: date,
        end_date: date,
        company_id: str = "default",
        exclude_leave_id: Optional[str] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Check if leave has conflicts with existing leaves.

        Returns:
            has_conflict, list of conflicting leave_request_ids
        """
        overlapping = await self.leave_repo.find_overlapping_leaves(
            employee_id=employee_id,
            start_date=start_date,
            end_date=end_date,
            company_id=company_id,
            exclude_leave_id=exclude_leave_id,
        )

        if overlapping:
            conflict_ids = [
                leave.get("leave_request_id")
                for leave in overlapping
                if leave.get("leave_request_id")
            ]
            return True, conflict_ids

        return False, []

    def _build_summary(self, leave: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return leave dict safely.

        Routes/schemas handle final response validation.
        """
        return leave

    # -------------------------
    # Create leave request
    # -------------------------

    async def create_leave_request(
        self,
        employee_id: str,
        leave_type_id: str,
        start_date: date,
        end_date: date,
        reason: str,
        contact_during_leave: Optional[str] = None,
        handover_notes: Optional[str] = None,
        half_day_dates: Optional[List[date]] = None,
        half_day_types: Optional[List[LeaveDayType]] = None,
        is_emergency: bool = False,
        created_by: Optional[str] = None,
        company_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Create new leave request.

        Steps:
        1. Validate write mode
        2. Validate employee and leave type
        3. Calculate leave days
        4. Check balance
        5. Check conflicts
        6. Validate leave rules
        7. Build approval chain
        8. Create leave request
        9. Auto-deduct balance if no approval required
        """
        self._ensure_write_allowed()

        company_id = self._normalize_company_id(company_id)

        employee = await self._get_employee_or_raise(employee_id, company_id)
        leave_type = await self._get_leave_type_or_raise(leave_type_id, company_id)

        leave_days, total_days = await self._calculate_leave_days(
            start_date=start_date,
            end_date=end_date,
            half_day_dates=half_day_dates,
            half_day_types=half_day_types,
            company_id=company_id,
        )

        if total_days <= 0:
            raise ValueError(
                "All selected days are weekends or holidays. No leave deduction needed."
            )

        leave_type_code = str(leave_type["code"]).strip().upper()
        balance_before = await self._get_leave_balance(employee, leave_type_code)

        if balance_before < total_days:
            raise ValueError(
                f"Insufficient leave balance. Available: {balance_before}, Required: {total_days}"
            )

        has_conflict, conflict_ids = await self._check_leave_conflicts(
            employee_id=employee_id,
            start_date=start_date,
            end_date=end_date,
            company_id=company_id,
        )

        if has_conflict:
            raise ValueError(
                f"Leave conflicts with existing leave request(s): {', '.join(conflict_ids)}"
            )

        is_half_day = any(
            day.day_type in {LeaveDayType.FIRST_HALF, LeaveDayType.SECOND_HALF}
            for day in leave_days
        )

        self._validate_leave_rules(
            leave_type=leave_type,
            total_days=total_days,
            start_date=start_date,
            is_emergency=is_emergency,
            is_half_day=is_half_day,
            employee=employee,
        )

        is_backdated = start_date < date.today()

        if is_backdated and not leave_type.get("allow_backdated", False):
            raise ValueError(
                f"{leave_type.get('name', 'This leave type')} does not allow backdated applications"
            )

        approval_chain, current_approver_id, requires_hr, initial_status = await self._build_approval_chain(
            employee=employee,
            leave_type=leave_type,
            total_days=total_days,
            company_id=company_id,
        )

        leave_request_id = await self.leave_repo.generate_leave_request_id(
            company_id=company_id,
        )

        documentation_required = bool(leave_type.get("requires_documentation", False))

        documentation_threshold = leave_type.get("documentation_threshold")
        if documentation_threshold is not None:
            documentation_required = total_days >= float(documentation_threshold)

        now = datetime.utcnow()
        balance_after = None
        balance_action = LeaveBalanceAction.NONE
        balance_reserved = 0.0
        approved_date = None

        if initial_status == LeaveStatus.APPROVED:
            balance_after = balance_before - total_days
            balance_action = LeaveBalanceAction.DEDUCTED
            approved_date = now

        elif initial_status == LeaveStatus.PENDING:
            balance_reserved = total_days
            balance_action = LeaveBalanceAction.RESERVED

        employee_name = self._get_employee_full_name(employee)

        leave_data = {
            "company_id": company_id,
            "source": LeaveSource.LOCAL.value,
            "external_hrms_id": None,
            "is_read_only": False,
            "leave_request_id": leave_request_id,
            "employee_id": employee_id,
            "employee_code": employee.get("employee_code"),
            "employee_name": employee_name,
            "department_id": employee.get("department_id"),
            "department_name": self._get_department_name(employee),
            "manager_id": employee.get("manager_id"),
            "manager_name": self._get_manager_name(employee),
            "leave_type_id": leave_type_id,
            "leave_type_code": leave_type_code,
            "leave_type_name": leave_type.get("name"),
            "start_date": start_date,
            "end_date": end_date,
            "leave_days": [day.model_dump() for day in leave_days],
            "total_days": total_days,
            "reason": reason,
            "contact_during_leave": self._clean_text(contact_during_leave),
            "handover_notes": self._clean_text(handover_notes),
            "status": initial_status.value,
            "approval_chain": approval_chain,
            "current_approver_id": current_approver_id,
            "requires_hr_approval": requires_hr,
            "attachments": [],
            "documentation_required": documentation_required,
            "documentation_received": False,
            "balance_before": balance_before,
            "balance_reserved": balance_reserved,
            "balance_after": balance_after,
            "balance_action": balance_action.value,
            "policy_snapshot": self._build_policy_snapshot(leave_type).model_dump(),
            "is_emergency": is_emergency,
            "is_backdated": is_backdated,
            "is_half_day": is_half_day,
            "has_conflict": False,
            "conflict_leave_request_ids": [],
            "applied_date": now,
            "approved_date": approved_date,
            "rejected_date": None,
            "cancelled_date": None,
            "withdrawn_date": None,
            "cancellation_reason": None,
            "withdrawal_reason": None,
            "created_by": created_by or employee_id,
            "updated_by": None,
            "created_at": now,
            "updated_at": now,
        }

        leave_request = LeaveRequest(**leave_data)
        leave_id = await self.leave_repo.create(leave_request.model_dump())

        if initial_status == LeaveStatus.APPROVED:
            await self._update_leave_balance(
                employee_id=employee_id,
                leave_type_code=leave_type_code,
                amount=total_days,
                operation="deduct",
                company_id=company_id,
            )

        created_leave = await self.leave_repo.find_by_id(leave_id, company_id)

        if not created_leave:
            raise ValueError("Leave request created but could not be retrieved")

        return created_leave

    # -------------------------
    # Update leave request
    # -------------------------

    async def update_leave_request(
        self,
        leave_id: str,
        employee_id: str,
        update_data: Dict[str, Any],
        company_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Update leave request.

        Only creator/employee can update, and only editable statuses are allowed.
        """
        self._ensure_write_allowed()

        company_id = self._normalize_company_id(company_id)

        leave = await self.leave_repo.find_by_id(leave_id, company_id)

        if not leave:
            raise ValueError("Leave request not found")

        self._ensure_record_is_writable(leave)

        if leave.get("employee_id") != employee_id:
            raise ValueError("You can only update your own leave requests")

        if leave.get("status") not in self.EDITABLE_STATUSES:
            raise ValueError(f"Cannot update leave with status {leave.get('status')}")

        safe_update = {
            key: value
            for key, value in update_data.items()
            if value is not None
        }

        if not safe_update:
            raise ValueError("No update data provided")

        await self.leave_repo.update(
            leave_id=leave_id,
            update_data=safe_update,
            company_id=company_id,
        )

        updated_leave = await self.leave_repo.find_by_id(leave_id, company_id)

        if not updated_leave:
            raise ValueError("Leave updated but could not be retrieved")

        return updated_leave

    # -------------------------
    # Approve / Reject leave
    # -------------------------

    async def approve_leave(
        self,
        leave_id: str,
        approver_id: str,
        comments: Optional[str] = None,
        company_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Approve leave request.

        Logic:
        1. Verify approver is current approver
        2. Update approval step
        3. Move to next pending approval if any
        4. If fully approved, deduct balance
        """
        self._ensure_write_allowed()

        company_id = self._normalize_company_id(company_id)

        leave = await self.leave_repo.find_by_id(leave_id, company_id)

        if not leave:
            raise ValueError("Leave request not found")

        self._ensure_record_is_writable(leave)

        if leave.get("status") not in self.APPROVAL_STATUSES:
            raise ValueError(f"Leave is already {leave.get('status')}")

        if leave.get("current_approver_id") != approver_id:
            raise ValueError("You are not authorized to approve this leave")

        approval_chain = leave.get("approval_chain", [])
        updated_chain = False
        now = datetime.utcnow()

        for step in approval_chain:
            if (
                step.get("approver_id") == approver_id
                and step.get("status") == LeaveApprovalStatus.PENDING.value
            ):
                step["status"] = LeaveApprovalStatus.APPROVED.value
                step["comments"] = self._clean_text(comments)
                step["action_date"] = now
                updated_chain = True
                break

        if not updated_chain:
            raise ValueError("Approval step not found or already processed")

        pending_steps = [
            step for step in approval_chain
            if step.get("status") == LeaveApprovalStatus.PENDING.value
        ]

        balance_after = None
        extra_fields: Dict[str, Any] = {}

        if pending_steps:
            next_approver = sorted(
                pending_steps,
                key=lambda item: item.get("step_order", 999),
            )[0]

            new_status = LeaveStatus.MANAGER_APPROVED.value
            current_approver_id = next_approver.get("approver_id")

        else:
            new_status = LeaveStatus.APPROVED.value
            current_approver_id = None

            balance_before = float(leave.get("balance_before", 0.0) or 0.0)
            total_days = float(leave.get("total_days", 0.0) or 0.0)
            balance_after = balance_before - total_days

            await self._update_leave_balance(
                employee_id=leave["employee_id"],
                leave_type_code=leave["leave_type_code"],
                amount=total_days,
                operation="deduct",
                company_id=company_id,
            )

            extra_fields.update(
                {
                    "approved_date": now,
                    "balance_after": balance_after,
                    "balance_reserved": 0.0,
                    "balance_action": LeaveBalanceAction.DEDUCTED.value,
                }
            )

        await self.leave_repo.update_approval_chain(
            leave_id=leave_id,
            approval_chain=approval_chain,
            current_approver_id=current_approver_id,
            updated_by=approver_id,
            company_id=company_id,
            status=new_status,
            extra_fields=extra_fields,
        )

        updated_leave = await self.leave_repo.find_by_id(leave_id, company_id)

        if not updated_leave:
            raise ValueError("Leave approved but could not be retrieved")

        return updated_leave

    async def reject_leave(
        self,
        leave_id: str,
        approver_id: str,
        rejection_reason: LeaveRejectionReason,
        comments: str,
        company_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Reject leave request.
        """
        self._ensure_write_allowed()

        company_id = self._normalize_company_id(company_id)

        leave = await self.leave_repo.find_by_id(leave_id, company_id)

        if not leave:
            raise ValueError("Leave request not found")

        self._ensure_record_is_writable(leave)

        if leave.get("status") not in self.APPROVAL_STATUSES:
            raise ValueError(f"Leave is already {leave.get('status')}")

        if leave.get("current_approver_id") != approver_id:
            raise ValueError("You are not authorized to reject this leave")

        approval_chain = leave.get("approval_chain", [])
        updated_chain = False
        now = datetime.utcnow()

        for step in approval_chain:
            if (
                step.get("approver_id") == approver_id
                and step.get("status") == LeaveApprovalStatus.PENDING.value
            ):
                step["status"] = LeaveApprovalStatus.REJECTED.value
                step["comments"] = comments
                step["rejection_reason"] = rejection_reason.value
                step["action_date"] = now
                updated_chain = True
                break

        if not updated_chain:
            raise ValueError("Approval step not found or already processed")

        extra_fields = {
            "rejected_date": now,
            "balance_reserved": 0.0,
            "balance_action": LeaveBalanceAction.RELEASED.value,
        }

        await self.leave_repo.update_approval_chain(
            leave_id=leave_id,
            approval_chain=approval_chain,
            current_approver_id=None,
            updated_by=approver_id,
            company_id=company_id,
            status=LeaveStatus.REJECTED.value,
            extra_fields=extra_fields,
        )

        updated_leave = await self.leave_repo.find_by_id(leave_id, company_id)

        if not updated_leave:
            raise ValueError("Leave rejected but could not be retrieved")

        return updated_leave

    # -------------------------
    # Cancel / Withdraw leave
    # -------------------------

    async def cancel_leave(
        self,
        leave_id: str,
        employee_id: str,
        cancellation_reason: str,
        company_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Cancel leave request.

        Allowed for:
        - draft
        - pending
        - manager_approved
        - approved leave only if start date is in future
        """
        self._ensure_write_allowed()

        company_id = self._normalize_company_id(company_id)

        leave = await self.leave_repo.find_by_id(leave_id, company_id)

        if not leave:
            raise ValueError("Leave request not found")

        self._ensure_record_is_writable(leave)

        if leave.get("employee_id") != employee_id:
            raise ValueError("You can only cancel your own leave requests")

        status = leave.get("status")
        now = datetime.utcnow()

        if status in {LeaveStatus.REJECTED.value, LeaveStatus.CANCELLED.value, LeaveStatus.WITHDRAWN.value}:
            raise ValueError(f"Cannot cancel {status} leave")

        if status == LeaveStatus.APPROVED.value:
            leave_start_date = leave.get("start_date")

            if isinstance(leave_start_date, datetime):
                leave_start_date = leave_start_date.date()

            if leave_start_date and leave_start_date < date.today():
                raise ValueError("Cannot cancel approved leave that has already started")

            await self._update_leave_balance(
                employee_id=employee_id,
                leave_type_code=leave["leave_type_code"],
                amount=float(leave["total_days"]),
                operation="restore",
                company_id=company_id,
            )

        update_data = {
            "status": LeaveStatus.CANCELLED.value,
            "cancellation_reason": cancellation_reason,
            "cancelled_date": now,
            "current_approver_id": None,
            "updated_by": employee_id,
            "balance_reserved": 0.0,
            "balance_action": LeaveBalanceAction.RELEASED.value,
        }

        await self.leave_repo.update(
            leave_id,
            update_data,
            company_id,
        )

        updated_leave = await self.leave_repo.find_by_id(leave_id, company_id)

        if not updated_leave:
            raise ValueError("Leave cancelled but could not be retrieved")

        return updated_leave

    async def withdraw_leave(
        self,
        leave_id: str,
        employee_id: str,
        withdrawal_reason: str,
        company_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Withdraw an approved leave.

        This is different from cancellation:
        - cancellation is before final approval or before leave starts
        - withdrawal is for approved leave where company allows withdrawal
        """
        self._ensure_write_allowed()

        company_id = self._normalize_company_id(company_id)

        leave = await self.leave_repo.find_by_id(leave_id, company_id)

        if not leave:
            raise ValueError("Leave request not found")

        self._ensure_record_is_writable(leave)

        if leave.get("employee_id") != employee_id:
            raise ValueError("You can only withdraw your own leave requests")

        if leave.get("status") != LeaveStatus.APPROVED.value:
            raise ValueError("Only approved leave can be withdrawn")

        leave_start_date = leave.get("start_date")

        if isinstance(leave_start_date, datetime):
            leave_start_date = leave_start_date.date()

        if leave_start_date and leave_start_date < date.today():
            raise ValueError("Cannot withdraw leave that has already started")

        await self._update_leave_balance(
            employee_id=employee_id,
            leave_type_code=leave["leave_type_code"],
            amount=float(leave["total_days"]),
            operation="restore",
            company_id=company_id,
        )

        update_data = {
            "status": LeaveStatus.WITHDRAWN.value,
            "withdrawal_reason": withdrawal_reason,
            "withdrawn_date": datetime.utcnow(),
            "current_approver_id": None,
            "updated_by": employee_id,
            "balance_reserved": 0.0,
            "balance_action": LeaveBalanceAction.RELEASED.value,
        }

        await self.leave_repo.update(
            leave_id,
            update_data,
            company_id,
        )

        updated_leave = await self.leave_repo.find_by_id(leave_id, company_id)

        if not updated_leave:
            raise ValueError("Leave withdrawn but could not be retrieved")

        return updated_leave

    # -------------------------
    # Attachment methods
    # -------------------------

    async def add_attachment(
        self,
        leave_id: str,
        attachment_data: Dict[str, Any],
        uploaded_by: str,
        company_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Add attachment metadata to leave request.
        """
        self._ensure_write_allowed()

        company_id = self._normalize_company_id(company_id)

        leave = await self.leave_repo.find_by_id(leave_id, company_id)

        if not leave:
            raise ValueError("Leave request not found")

        self._ensure_record_is_writable(leave)

        if leave.get("employee_id") != uploaded_by:
            raise ValueError("You can only upload attachment to your own leave request")

        attachment_data["uploaded_by"] = uploaded_by
        attachment_data["uploaded_at"] = datetime.utcnow()

        attachment = LeaveAttachment(**attachment_data)
        attachments = leave.get("attachments", [])
        attachments.append(attachment.model_dump())

        update_data = {
            "attachments": attachments,
            "documentation_received": True,
            "updated_by": uploaded_by,
        }

        await self.leave_repo.update(
            leave_id=leave_id,
            update_data=update_data,
            company_id=company_id,
        )

        updated_leave = await self.leave_repo.find_by_id(leave_id, company_id)

        if not updated_leave:
            raise ValueError("Attachment added but leave could not be retrieved")

        return updated_leave

    # -------------------------
    # Query methods
    # -------------------------

    async def get_leave_by_id(
        self,
        leave_id: str,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Get leave request by ID.
        """
        return await self.leave_repo.find_by_id(leave_id, company_id)

    async def get_leave_by_request_id(
        self,
        leave_request_id: str,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Get leave request by leave_request_id.
        """
        return await self.leave_repo.find_by_leave_request_id(
            leave_request_id,
            company_id,
        )

    async def list_employee_leaves(
        self,
        employee_id: str,
        company_id: str = "default",
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        List leaves for an employee with total count.
        """
        leaves = await self.leave_repo.list_by_employee(
            employee_id=employee_id,
            company_id=company_id,
            status=status,
            skip=skip,
            limit=limit,
        )

        total = await self.leave_repo.count_by_employee(
            employee_id=employee_id,
            company_id=company_id,
            status=status,
        )

        return leaves, total

    async def list_leaves_with_filters(
        self,
        company_id: str = "default",
        employee_id: Optional[str] = None,
        employee_code: Optional[str] = None,
        status: Optional[str] = None,
        statuses: Optional[List[str]] = None,
        leave_type_id: Optional[str] = None,
        leave_type_code: Optional[str] = None,
        department_id: Optional[str] = None,
        manager_id: Optional[str] = None,
        current_approver_id: Optional[str] = None,
        source: Optional[str] = None,
        is_read_only: Optional[bool] = None,
        start_date_from: Optional[date] = None,
        start_date_to: Optional[date] = None,
        applied_date_from: Optional[date] = None,
        applied_date_to: Optional[date] = None,
        is_emergency: Optional[bool] = None,
        is_backdated: Optional[bool] = None,
        is_half_day: Optional[bool] = None,
        has_conflict: Optional[bool] = None,
        documentation_required: Optional[bool] = None,
        documentation_received: Optional[bool] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
        sort_by: str = "applied_date",
        sort_order: str = "desc",
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        List leaves using advanced filters.
        """
        leaves = await self.leave_repo.list_with_filters(
            company_id=company_id,
            employee_id=employee_id,
            employee_code=employee_code,
            status=status,
            statuses=statuses,
            leave_type_id=leave_type_id,
            leave_type_code=leave_type_code,
            department_id=department_id,
            manager_id=manager_id,
            current_approver_id=current_approver_id,
            source=source,
            is_read_only=is_read_only,
            start_date_from=start_date_from,
            start_date_to=start_date_to,
            applied_date_from=applied_date_from,
            applied_date_to=applied_date_to,
            is_emergency=is_emergency,
            is_backdated=is_backdated,
            is_half_day=is_half_day,
            has_conflict=has_conflict,
            documentation_required=documentation_required,
            documentation_received=documentation_received,
            search=search,
            skip=skip,
            limit=limit,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        total = await self.leave_repo.count_with_filters(
            company_id=company_id,
            employee_id=employee_id,
            employee_code=employee_code,
            status=status,
            statuses=statuses,
            leave_type_id=leave_type_id,
            leave_type_code=leave_type_code,
            department_id=department_id,
            manager_id=manager_id,
            current_approver_id=current_approver_id,
            source=source,
            is_read_only=is_read_only,
            start_date_from=start_date_from,
            start_date_to=start_date_to,
            applied_date_from=applied_date_from,
            applied_date_to=applied_date_to,
            is_emergency=is_emergency,
            is_backdated=is_backdated,
            is_half_day=is_half_day,
            has_conflict=has_conflict,
            documentation_required=documentation_required,
            documentation_received=documentation_received,
            search=search,
        )

        return leaves, total

    async def list_pending_approvals(
        self,
        approver_id: str,
        company_id: str = "default",
        skip: int = 0,
        limit: int = 100,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        List leaves pending approval for an approver.
        """
        leaves = await self.leave_repo.list_pending_approvals(
            approver_id=approver_id,
            company_id=company_id,
            skip=skip,
            limit=limit,
        )

        total = await self.leave_repo.count_pending_approvals(
            approver_id=approver_id,
            company_id=company_id,
        )

        return leaves, total

    async def get_leave_statistics(
        self,
        employee_id: str,
        company_id: str = "default",
        year: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get leave statistics for employee.
        """
        return await self.leave_repo.get_leave_statistics(
            employee_id=employee_id,
            company_id=company_id,
            year=year,
        )

    async def get_dashboard_statistics(
        self,
        company_id: str = "default",
        year: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get company-wide leave dashboard statistics.
        """
        return await self.leave_repo.get_dashboard_statistics(
            company_id=company_id,
            year=year,
        )

    async def get_statistics_by_leave_type(
        self,
        company_id: str = "default",
        year: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get leave statistics grouped by leave type.
        """
        return await self.leave_repo.get_statistics_by_leave_type(
            company_id=company_id,
            year=year,
        )

    async def get_upcoming_leaves(
        self,
        employee_id: str,
        company_id: str = "default",
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Get upcoming approved leaves.
        """
        return await self.leave_repo.list_upcoming_leaves(
            employee_id=employee_id,
            company_id=company_id,
            limit=limit,
        )

    async def get_calendar_leaves(
        self,
        start_date: date,
        end_date: date,
        company_id: str = "default",
        department_id: Optional[str] = None,
        manager_id: Optional[str] = None,
        include_pending: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get leave records for calendar.
        """
        return await self.leave_repo.get_calendar_leaves(
            start_date=start_date,
            end_date=end_date,
            company_id=company_id,
            department_id=department_id,
            manager_id=manager_id,
            include_pending=include_pending,
        )

    async def get_leave_balance(
        self,
        employee_id: str,
        leave_type_code: str,
        company_id: str = "default",
        year: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get employee leave balance for one leave type.
        """
        employee = await self._get_employee_or_raise(employee_id, company_id)

        leave_type_code = str(leave_type_code).strip().upper()
        leave_balances = employee.get("leave_balances", [])

        for balance in leave_balances:
            if str(balance.get("leave_type_code", "")).strip().upper() == leave_type_code:
                if year is None or balance.get("year") is None or int(balance.get("year")) == int(year):
                    return {
                        "employee_id": employee_id,
                        "employee_code": employee.get("employee_code"),
                        "leave_type_code": leave_type_code,
                        "leave_type_name": balance.get("leave_type_name", leave_type_code),
                        "granted": float(balance.get("granted", 0.0) or 0.0),
                        "used": float(balance.get("used", 0.0) or 0.0),
                        "available": float(balance.get("available", 0.0) or 0.0),
                        "carried_forward": float(balance.get("carried_forward", 0.0) or 0.0),
                        "encashed": float(balance.get("encashed", 0.0) or 0.0),
                        "year": int(balance.get("year") or datetime.utcnow().year),
                    }

        raise ValueError(f"Leave balance not found for leave type {leave_type_code}")

    # -------------------------
    # HRMS import/read-only helper
    # -------------------------

    async def import_hrms_leave_record(
        self,
        leave_data: Dict[str, Any],
        imported_by: str,
    ) -> Dict[str, Any]:
        """
        Import HRMS leave record as read-only.

        Use only in controlled sync/admin process.
        """
        company_id = self._normalize_company_id(leave_data.get("company_id", "default"))
        external_hrms_id = leave_data.get("external_hrms_id")

        if not external_hrms_id:
            raise ValueError("external_hrms_id is required")

        existing = await self.leave_repo.find_by_external_hrms_id(
            external_hrms_id=external_hrms_id,
            company_id=company_id,
        )

        if existing:
            return existing

        now = datetime.utcnow()

        leave_request_id = await self.leave_repo.generate_leave_request_id(
            prefix="HRMS-LV",
            company_id=company_id,
        )

        data = {
            **leave_data,
            "company_id": company_id,
            "source": LeaveSource.HRMS.value,
            "is_read_only": True,
            "leave_request_id": leave_request_id,
            "leave_days": leave_data.get("leave_days", []),
            "approval_chain": leave_data.get("approval_chain", []),
            "current_approver_id": None,
            "requires_hr_approval": False,
            "attachments": leave_data.get("attachments", []),
            "documentation_required": leave_data.get("documentation_required", False),
            "documentation_received": leave_data.get("documentation_received", False),
            "balance_before": float(leave_data.get("balance_before", 0.0) or 0.0),
            "balance_reserved": 0.0,
            "balance_after": leave_data.get("balance_after"),
            "balance_action": LeaveBalanceAction.NONE.value,
            "policy_snapshot": None,
            "is_emergency": leave_data.get("is_emergency", False),
            "is_backdated": leave_data.get("is_backdated", False),
            "is_half_day": leave_data.get("is_half_day", False),
            "has_conflict": False,
            "conflict_leave_request_ids": [],
            "applied_date": leave_data.get("applied_date", now),
            "approved_date": leave_data.get("approved_date"),
            "rejected_date": leave_data.get("rejected_date"),
            "cancelled_date": leave_data.get("cancelled_date"),
            "withdrawn_date": leave_data.get("withdrawn_date"),
            "cancellation_reason": leave_data.get("cancellation_reason"),
            "withdrawal_reason": leave_data.get("withdrawal_reason"),
            "created_by": imported_by,
            "updated_by": None,
            "created_at": now,
            "updated_at": now,
        }

        leave_request = LeaveRequest(**data)
        leave_id = await self.leave_repo.create(leave_request.model_dump())

        imported_leave = await self.leave_repo.find_by_id(leave_id, company_id)

        if not imported_leave:
            raise ValueError("HRMS leave imported but could not be retrieved")

        return imported_leave

    # -------------------------
    # Capability helper
    # -------------------------

    def get_capabilities(self) -> Dict[str, Any]:
        """
        Return leave module capabilities based on deployment mode.
        """
        if self.mode == "hrms_readonly":
            return {
                "mode": "hrms_readonly",
                "can_create_leave": False,
                "can_update_leave": False,
                "can_approve_leave": False,
                "can_cancel_leave": False,
                "can_read_hrms": True,
                "stores_leave_locally": False,
            }

        if self.mode == "hrms_write_approved":
            return {
                "mode": "hrms_write_approved",
                "can_create_leave": True,
                "can_update_leave": True,
                "can_approve_leave": True,
                "can_cancel_leave": True,
                "can_read_hrms": True,
                "stores_leave_locally": True,
            }

        return {
            "mode": "local_mvp",
            "can_create_leave": True,
            "can_update_leave": True,
            "can_approve_leave": True,
            "can_cancel_leave": True,
            "can_read_hrms": False,
            "stores_leave_locally": True,
        }