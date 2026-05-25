"""
Claim service - Business logic layer for claim/reimbursement management.

Pattern:
Route -> Service -> Repository -> MongoDB

This service handles:
- Claim creation and draft creation
- Employee snapshot creation
- Claim type snapshot creation
- Policy snapshot creation
- Duplicate detection
- Claim limit checking
- Bill/attachment validation
- Structured approval workflow
- HRMS/import read-only compatibility
- Payment processing
- Statistics and dashboard data

Important production rules:
- LLM must never directly access DB.
- Routes/tools call this service.
- Service validates business rules before repository writes.
- Repository only performs MongoDB operations.
- MongoDB is mock HRMS for MVP.
- In production, external HRMS can be source of truth.
- AI must never approve claims.
- Auto approval is disabled in service logic.
- Every submitted claim must go through manager/finance/HR approval.
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime as DateTime
from math import ceil
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from backend.app.models.claim_model import (
    Claim,
    ClaimActionHistory,
    ClaimActionType,
    ClaimApprovalStep,
    ClaimApprovalStatus,
    ClaimApproverRole,
    ClaimAttachment,
    ClaimDashboardStatistics,
    ClaimPaymentStatus,
    ClaimPolicySnapshot,
    ClaimPrivateResponse,
    ClaimResponse,
    ClaimSource,
    ClaimStatistics,
    ClaimStatus,
    ClaimSummary,
)
from backend.app.repositories.claim_repository import ClaimRepository
from backend.app.schemas.claim_schema import (
    AddClaimAttachmentRequest,
    ApproveClaimRequest,
    CancelClaimRequest,
    ClaimDashboardFilters,
    ClaimListFilters,
    ClaimValidationResponse,
    CreateClaimDraftRequest,
    CreateClaimRequest,
    ImportClaimFromHRMSRequest,
    MarkClaimPaidRequest,
    MarkClaimPaymentFailedRequest,
    PendingApprovalsFilters,
    RejectClaimRequest,
    ResubmitClaimRequest,
    SendBackClaimRequest,
    StartClaimPaymentProcessingRequest,
    SubmitClaimRequest,
    UpdateClaimRequest,
    UpdatePaymentStatusRequest,
    ValidateClaimRequest,
    VerifyClaimAttachmentRequest,
    WithdrawClaimRequest,
)


class ClaimService:
    """
    Service for claim business logic.

    This service returns:
        Tuple[bool, Dict[str, Any]]

    This keeps it compatible with your current route pattern.
    Routes can later be upgraded to directly return Pydantic responses.
    """

    FINAL_STATUSES = {
        ClaimStatus.PAID.value,
        ClaimStatus.REJECTED.value,
        ClaimStatus.CANCELLED.value,
        ClaimStatus.WITHDRAWN.value,
        ClaimStatus.FAILED.value,
    }

    EDITABLE_STATUSES = {
        ClaimStatus.DRAFT.value,
        ClaimStatus.SENT_BACK.value,
    }

    SUBMITTABLE_STATUSES = {
        ClaimStatus.DRAFT.value,
        ClaimStatus.SENT_BACK.value,
    }

    APPROVABLE_STATUSES = {
        ClaimStatus.PENDING.value,
        ClaimStatus.RESUBMITTED.value,
        ClaimStatus.MANAGER_APPROVED.value,
        ClaimStatus.FINANCE_APPROVED.value,
    }

    CANCELLABLE_STATUSES = {
        ClaimStatus.DRAFT.value,
        ClaimStatus.PENDING.value,
        ClaimStatus.RESUBMITTED.value,
        ClaimStatus.SENT_BACK.value,
        ClaimStatus.MANAGER_APPROVED.value,
        ClaimStatus.FINANCE_APPROVED.value,
        ClaimStatus.APPROVED.value,
    }

    WITHDRAWABLE_STATUSES = {
        ClaimStatus.PENDING.value,
        ClaimStatus.RESUBMITTED.value,
        ClaimStatus.SENT_BACK.value,
        ClaimStatus.MANAGER_APPROVED.value,
        ClaimStatus.FINANCE_APPROVED.value,
    }

    def __init__(
        self,
        claim_repo: ClaimRepository,
        claim_type_repo,
        employee_repo,
        company_settings_repo=None,
    ):
        """
        Initialize claim service.

        Args:
            claim_repo: ClaimRepository instance
            claim_type_repo: Claim type repository instance
            employee_repo: Employee repository instance
            company_settings_repo: Optional company settings repository/service
        """
        self.claim_repo = claim_repo
        self.claim_type_repo = claim_type_repo
        self.employee_repo = employee_repo
        self.company_settings_repo = company_settings_repo

    # ---------------------------------------------------------------------
    # Response helpers
    # ---------------------------------------------------------------------

    def _success(
        self,
        data: Optional[Dict[str, Any]] = None,
        message: str = "Success",
    ) -> Dict[str, Any]:
        return {
            "success": True,
            "message": message,
            "data": data or {},
        }

    def _error(
        self,
        error_code: str,
        message: str,
        details: Optional[Any] = None,
    ) -> Dict[str, Any]:
        response = {
            "success": False,
            "error_code": error_code,
            "message": message,
        }

        if details is not None:
            response["details"] = details

        return response

    # ---------------------------------------------------------------------
    # Generic helpers
    # ---------------------------------------------------------------------

    def _normalize_company_id(self, company_id: Optional[str] = "default") -> str:
        if not company_id:
            return "default"

        company_id = str(company_id).strip().lower()
        return company_id or "default"

    def _enum_value(self, value: Any) -> Any:
        if hasattr(value, "value"):
            return value.value
        return value

    def _model_to_dict(
        self,
        value: Any,
        exclude_none: bool = False,
        exclude_unset: bool = False,
    ) -> Dict[str, Any]:
        if hasattr(value, "model_dump"):
            return value.model_dump(
                exclude_none=exclude_none,
                exclude_unset=exclude_unset,
            )

        if isinstance(value, dict):
            return dict(value)

        return {}

    def _clean_response_document(self, document: Dict[str, Any]) -> Dict[str, Any]:
        cleaned = dict(document)

        if "_id" in cleaned:
            cleaned["_id"] = str(cleaned["_id"])
            cleaned["id"] = cleaned["_id"]

        return cleaned

    async def _call_repo_method(
        self,
        repo: Any,
        method_names: List[str],
        *args,
        **kwargs,
    ) -> Any:
        """
        Calls the first existing async method from a repository.

        This keeps this service compatible with slightly different repository
        method names while the project is evolving.
        """
        for method_name in method_names:
            method = getattr(repo, method_name, None)

            if method is not None:
                return await method(*args, **kwargs)

        raise AttributeError(
            f"None of these repository methods exist: {', '.join(method_names)}"
        )

    # ---------------------------------------------------------------------
    # ID generation
    # ---------------------------------------------------------------------

    async def _generate_claim_id(self, company_id: str = "default") -> str:
        """
        Generate claim ID in CLM-YYYY-0001 format.

        MVP approach:
        - Uses count as simple sequence.
        - In production, replace with atomic counter collection.
        """
        year = Date.today().year

        total_this_year = await self.claim_repo.count_claims(
            company_id=company_id,
            from_date=Date(year, 1, 1),
            to_date=Date(year, 12, 31),
        )

        sequence = total_this_year + 1

        for _ in range(20):
            claim_id = f"CLM-{year}-{sequence:04d}"

            exists = await self.claim_repo.claim_id_exists(
                claim_id=claim_id,
                company_id=company_id,
            )

            if not exists:
                return claim_id

            sequence += 1

        raise RuntimeError("Failed to generate unique claim ID")

    # ---------------------------------------------------------------------
    # Trusted data fetching helpers
    # ---------------------------------------------------------------------

    async def _get_employee_or_error(
        self,
        employee_id: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Get employee document.
        """
        try:
            employee = await self._call_repo_method(
                self.employee_repo,
                ["find_by_id", "get_by_id", "find_by_employee_id"],
                employee_id,
            )
        except Exception as exc:
            return None, self._error(
                "EMPLOYEE_LOOKUP_FAILED",
                f"Failed to lookup employee: {str(exc)}",
            )

        if not employee:
            return None, self._error(
                "EMPLOYEE_NOT_FOUND",
                "Employee profile not found",
            )

        return employee, None

    async def _get_claim_type_or_error(
        self,
        claim_type_id: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Get claim type document.
        """
        try:
            claim_type = await self._call_repo_method(
                self.claim_type_repo,
                ["find_by_id", "get_by_id", "find_by_claim_type_id"],
                claim_type_id,
            )
        except Exception as exc:
            return None, self._error(
                "CLAIM_TYPE_LOOKUP_FAILED",
                f"Failed to lookup claim type: {str(exc)}",
            )

        if not claim_type:
            return None, self._error(
                "CLAIM_TYPE_NOT_FOUND",
                f"Claim type {claim_type_id} not found",
            )

        if claim_type.get("is_active") is False:
            return None, self._error(
                "CLAIM_TYPE_INACTIVE",
                "This claim type is currently inactive",
            )

        return claim_type, None

    async def _get_company_claim_policy(
        self,
        company_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Get company-level claim policy from company settings.

        Auto approval default is disabled.
        AI/service must not approve claims automatically.
        """
        default_policy = {
            "require_bill_above": 500.0,
            "max_bill_file_size_mb": 10,
            "allowed_bill_formats": ["pdf", "jpg", "jpeg", "png", "doc", "docx"],
            "enable_manager_approval": True,
            "manager_approval_threshold": 0.0,
            "enable_finance_approval": True,
            "finance_approval_threshold": 20000.0,
            "enable_auto_approval": False,
            "auto_approval_threshold": 0.0,
            "claim_submission_deadline_days": 30,
            "allow_advance_claim": False,
            "reimbursement_processing_days": 7,
        }

        if self.company_settings_repo is None:
            return default_policy

        try:
            if hasattr(self.company_settings_repo, "get_claim_policy_config"):
                policy = await self.company_settings_repo.get_claim_policy_config(
                    company_id=company_id
                )
            elif hasattr(self.company_settings_repo, "get_claim_policy"):
                result = await self.company_settings_repo.get_claim_policy(
                    company_id=company_id
                )
                policy = result.get("section_data", result) if isinstance(result, dict) else {}
            else:
                policy = None

            if not policy:
                return default_policy

            merged = dict(default_policy)
            merged.update(policy)

            # Hard safety fallback:
            # Even if company settings still has old defaults, service does not auto approve.
            merged.setdefault("enable_auto_approval", False)
            merged.setdefault("auto_approval_threshold", 0.0)

            return merged

        except Exception:
            return default_policy

    # ---------------------------------------------------------------------
    # Snapshot builders
    # ---------------------------------------------------------------------

    def _build_employee_snapshot(self, employee: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build employee snapshot fields for claim document.

        This prevents old claims changing if employee department/name changes later.
        """
        first_name = employee.get("first_name") or employee.get("firstName") or ""
        last_name = employee.get("last_name") or employee.get("lastName") or ""

        full_name = (
            employee.get("employee_name")
            or employee.get("full_name")
            or employee.get("name")
            or f"{first_name} {last_name}".strip()
        )

        employee_id = (
            employee.get("id")
            or employee.get("_id")
            or employee.get("employee_id")
        )

        return {
            "employee_id": str(employee_id),
            "employee_code": str(
                employee.get("employee_code")
                or employee.get("code")
                or employee.get("emp_code")
                or employee.get("employee_number")
                or ""
            ),
            "employee_name": full_name or "Unknown Employee",
            "department_id": employee.get("department_id"),
            "department_name": employee.get("department_name")
            or employee.get("department"),
            "manager_id": employee.get("manager_id"),
            "manager_name": employee.get("manager_name"),
        }

    def _build_claim_type_snapshot(
        self,
        claim_type: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build claim type snapshot fields.
        """
        claim_type_id = (
            claim_type.get("id")
            or claim_type.get("_id")
            or claim_type.get("claim_type_id")
        )

        return {
            "claim_type_id": str(claim_type_id),
            "claim_type_code": str(
                claim_type.get("code")
                or claim_type.get("claim_type_code")
                or claim_type.get("name")
                or ""
            ).upper(),
            "claim_type_name": str(
                claim_type.get("name")
                or claim_type.get("claim_type_name")
                or claim_type.get("code")
                or "Claim Type"
            ),
        }

    def _build_policy_snapshot(
        self,
        claim_type: Dict[str, Any],
        company_policy: Dict[str, Any],
        currency: str,
    ) -> ClaimPolicySnapshot:
        """
        Build effective claim policy snapshot.

        Important:
        - auto_approve_below may be stored for reference only.
        - AI/service must not auto-approve money claims.
        - Claims must go through approval workflow by default.
        """

        requires_bill = bool(
            claim_type.get(
                "requires_bill",
                company_policy.get("requires_bill", False),
            )
        )

        # Force approval for money-related claims.
        # Do not trust claim_type.requires_approval=False for local auto approval.
        requires_approval = True

        auto_approve_below = claim_type.get(
            "auto_approve_below",
            company_policy.get("auto_approval_threshold"),
        )

        finance_approval_threshold = claim_type.get(
            "finance_approval_threshold",
            company_policy.get("finance_approval_threshold"),
        )

        manager_approval_threshold = claim_type.get(
            "manager_approval_threshold",
            company_policy.get("manager_approval_threshold"),
        )

        max_claim_amount = claim_type.get("max_claim_amount")

        monthly_limit = claim_type.get(
            "default_monthly_limit",
            claim_type.get("monthly_limit"),
        )

        yearly_limit = claim_type.get(
            "default_annual_limit",
            claim_type.get("yearly_limit"),
        )

        allowed_file_types = claim_type.get(
            "allowed_file_types",
            claim_type.get(
                "allowed_bill_formats",
                company_policy.get(
                    "allowed_bill_formats",
                    ["pdf", "jpg", "jpeg", "png", "doc", "docx"],
                ),
            ),
        )

        return ClaimPolicySnapshot(
            requires_bill=requires_bill,
            require_bill_above=company_policy.get("require_bill_above"),
            requires_approval=requires_approval,
            auto_approve_below=auto_approve_below,  # stored only, not used for approval
            manager_approval_threshold=manager_approval_threshold,
            finance_approval_threshold=finance_approval_threshold,
            max_claim_amount=max_claim_amount,
            monthly_limit=monthly_limit,
            yearly_limit=yearly_limit,
            allowed_file_types=allowed_file_types,
            allowed_currency=currency,
            claim_submission_deadline_days=company_policy.get(
                "claim_submission_deadline_days"
            ),
            reimbursement_processing_days=company_policy.get(
                "reimbursement_processing_days"
            ),
            captured_at=DateTime.utcnow(),
        )

    def _build_approval_steps(
        self,
        amount: float,
        employee_snapshot: Dict[str, Any],
        policy_snapshot: ClaimPolicySnapshot,
    ) -> List[ClaimApprovalStep]:
        """
        Build structured approval workflow.

        Money-related claims must always go through human approval.
        AI must never approve claims.

        Flow:
        - Manager approval if manager exists.
        - HR approval fallback if manager does not exist.
        - Finance approval if amount reaches finance threshold.
        """

        steps: List[ClaimApprovalStep] = []
        step_order = 1

        manager_id = employee_snapshot.get("manager_id")
        manager_name = employee_snapshot.get("manager_name")

        if manager_id:
            steps.append(
                ClaimApprovalStep(
                    step_order=step_order,
                    approver_role=ClaimApproverRole.MANAGER,
                    approver_id=manager_id,
                    approver_name=manager_name,
                    approval_status=ClaimApprovalStatus.PENDING,
                )
            )
        else:
            steps.append(
                ClaimApprovalStep(
                    step_order=step_order,
                    approver_role=ClaimApproverRole.HR,
                    approval_status=ClaimApprovalStatus.PENDING,
                )
            )

        step_order += 1

        finance_threshold = policy_snapshot.finance_approval_threshold

        if finance_threshold is not None and amount >= finance_threshold:
            steps.append(
                ClaimApprovalStep(
                    step_order=step_order,
                    approver_role=ClaimApproverRole.FINANCE,
                    approval_status=ClaimApprovalStatus.PENDING,
                )
            )

        return steps

    def _build_action_event(
        self,
        action: ClaimActionType,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
        actor_role: Optional[str] = None,
        old_status: Optional[ClaimStatus] = None,
        new_status: Optional[ClaimStatus] = None,
        comments: Optional[str] = None,
        amount: Optional[float] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build action history event dict.
        """
        return ClaimActionHistory(
            action=action,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_status=old_status,
            new_status=new_status,
            comments=comments,
            amount=amount,
            action_at=DateTime.utcnow(),
            extra_data=extra_data or {},
        ).model_dump()

    # ---------------------------------------------------------------------
    # Conversion helpers
    # ---------------------------------------------------------------------

    def _to_claim_response(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert raw claim document to safe response dict.
        """
        claim = self._clean_response_document(claim)
        return ClaimResponse.model_validate(claim).model_dump()

    def _to_private_response(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert raw claim document to private response dict.
        """
        claim = self._clean_response_document(claim)
        return ClaimPrivateResponse.model_validate(claim).model_dump()

    def _to_summary(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert raw claim document to summary dict.
        """
        claim = self._clean_response_document(claim)

        if "has_attachments" not in claim:
            attachments = claim.get("attachments") or []
            claim["has_attachments"] = bool(attachments)
            claim["attachment_count"] = len(attachments)

        return ClaimSummary.model_validate(claim).model_dump()

    async def _get_claim_or_error(
        self,
        claim_id: str,
        company_id: str = "default",
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Get claim or return standard error.
        """
        claim = await self.claim_repo.find_by_claim_id(
            claim_id=claim_id,
            company_id=company_id,
        )

        if not claim:
            return None, self._error(
                "CLAIM_NOT_FOUND",
                f"Claim {claim_id} not found",
            )

        return claim, None

    def _is_read_only_claim(self, claim: Dict[str, Any]) -> bool:
        """
        Check if claim is HRMS/import read-only.
        """
        return bool(claim.get("is_read_only"))

    def _ensure_not_read_only(
        self,
        claim: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Prevent local edits to read-only HRMS claims.
        """
        if self._is_read_only_claim(claim):
            return self._error(
                "CLAIM_READ_ONLY",
                "This claim is read-only because it is owned by HRMS/import source",
            )

        return None

    def _ensure_owner(
        self,
        claim: Dict[str, Any],
        employee_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Ensure current employee owns the claim.
        """
        if str(claim.get("employee_id")) != str(employee_id):
            return self._error(
                "ACCESS_DENIED",
                "You can only access your own claim",
            )

        return None

    # ---------------------------------------------------------------------
    # Validation helpers
    # ---------------------------------------------------------------------

    async def _check_duplicate(
        self,
        employee_id: str,
        claim_type_id: str,
        amount: float,
        expense_date: Date,
        company_id: str,
        exclude_claim_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        duplicate = await self.claim_repo.find_recent_similar_claim(
            employee_id=employee_id,
            claim_type_id=claim_type_id,
            amount=amount,
            expense_date=expense_date,
            company_id=company_id,
            within_hours=48,
            exclude_claim_id=exclude_claim_id,
        )

        if duplicate:
            return self._error(
                "DUPLICATE_CLAIM",
                (
                    f"A similar claim ({duplicate.get('claim_id')}) already exists. "
                    "Please check your existing claims."
                ),
            )

        return None

    async def _check_claim_limit(
        self,
        employee_id: str,
        claim_type: Dict[str, Any],
        policy_snapshot: ClaimPolicySnapshot,
        amount: float,
        company_id: str,
    ) -> Dict[str, Any]:
        """
        Check max claim, monthly limit, and yearly limit.

        Uses repository only to read usage totals.
        """
        claim_type_id = str(
            claim_type.get("id")
            or claim_type.get("_id")
            or claim_type.get("claim_type_id")
        )

        claim_type_name = str(
            claim_type.get("name")
            or claim_type.get("claim_type_name")
            or "Claim Type"
        )

        if policy_snapshot.max_claim_amount is not None:
            if amount > policy_snapshot.max_claim_amount:
                return {
                    "claim_type_id": claim_type_id,
                    "claim_type_name": claim_type_name,
                    "can_claim": False,
                    "message": (
                        f"Claim amount exceeds maximum allowed amount "
                        f"{policy_snapshot.max_claim_amount:.2f}"
                    ),
                    "max_claim_amount": policy_snapshot.max_claim_amount,
                }

        current_year = Date.today().year
        current_month = Date.today().month

        monthly_used = await self.claim_repo.get_total_claimed_by_type(
            employee_id=employee_id,
            claim_type_id=claim_type_id,
            company_id=company_id,
            year=current_year,
            month=current_month,
        )

        yearly_used = await self.claim_repo.get_total_claimed_by_type(
            employee_id=employee_id,
            claim_type_id=claim_type_id,
            company_id=company_id,
            year=current_year,
        )

        monthly_limit = policy_snapshot.monthly_limit
        yearly_limit = policy_snapshot.yearly_limit

        if monthly_limit is not None and monthly_limit > 0:
            if monthly_used + amount > monthly_limit:
                return {
                    "claim_type_id": claim_type_id,
                    "claim_type_name": claim_type_name,
                    "can_claim": False,
                    "message": (
                        f"Claim exceeds monthly limit. Used: {monthly_used:.2f}, "
                        f"Limit: {monthly_limit:.2f}"
                    ),
                    "monthly_limit": monthly_limit,
                    "monthly_used_amount": monthly_used,
                    "monthly_remaining_amount": max(monthly_limit - monthly_used, 0),
                }

        if yearly_limit is not None and yearly_limit > 0:
            if yearly_used + amount > yearly_limit:
                return {
                    "claim_type_id": claim_type_id,
                    "claim_type_name": claim_type_name,
                    "can_claim": False,
                    "message": (
                        f"Claim exceeds yearly limit. Used: {yearly_used:.2f}, "
                        f"Limit: {yearly_limit:.2f}"
                    ),
                    "yearly_limit": yearly_limit,
                    "yearly_used_amount": yearly_used,
                    "yearly_remaining_amount": max(yearly_limit - yearly_used, 0),
                }

        return {
            "claim_type_id": claim_type_id,
            "claim_type_name": claim_type_name,
            "can_claim": True,
            "message": "Claim is within allowed limits",
            "monthly_limit": monthly_limit,
            "monthly_used_amount": monthly_used,
            "monthly_remaining_amount": (
                None if monthly_limit is None else max(monthly_limit - monthly_used, 0)
            ),
            "yearly_limit": yearly_limit,
            "yearly_used_amount": yearly_used,
            "yearly_remaining_amount": (
                None if yearly_limit is None else max(yearly_limit - yearly_used, 0)
            ),
            "max_claim_amount": policy_snapshot.max_claim_amount,
        }

    def _check_bill_requirement(
        self,
        amount: float,
        attachments_count: int,
        policy_snapshot: ClaimPolicySnapshot,
    ) -> Optional[Dict[str, Any]]:
        """
        Check whether attachment is required.

        Service rule:
        - if claim type says requires_bill=True, require attachment
        - if amount is above company require_bill_above, require attachment
        """
        requires_bill = policy_snapshot.requires_bill

        if (
            policy_snapshot.require_bill_above is not None
            and amount >= policy_snapshot.require_bill_above
        ):
            requires_bill = True

        if requires_bill and attachments_count <= 0:
            return self._error(
                "BILL_REQUIRED",
                "Bill/receipt attachment is required for this claim",
            )

        return None

    def _determine_initial_status_and_approval(
        self,
        amount: float,
        policy_snapshot: ClaimPolicySnapshot,
        approval_steps: List[ClaimApprovalStep],
        is_draft: bool = False,
    ) -> Tuple[
        ClaimStatus,
        bool,
        Optional[ClaimApproverRole],
        Optional[float],
        Optional[DateTime],
        Optional[str],
    ]:
        """
        Determine initial claim lifecycle values.

        Important:
        - No auto approval.
        - auto_approve_below is ignored here.
        - AI/service must never directly approve claims.
        - Every submitted claim starts as pending.
        """
        if is_draft:
            return ClaimStatus.DRAFT, True, None, None, None, None

        current_role = (
            approval_steps[0].approver_role
            if approval_steps
            else ClaimApproverRole.HR
        )

        return (
            ClaimStatus.PENDING,
            True,
            current_role,
            None,
            None,
            None,
        )

    # ---------------------------------------------------------------------
    # Create operations
    # ---------------------------------------------------------------------

    async def create_claim(
        self,
        employee_id: str,
        request: CreateClaimRequest,
        company_id: str = "default",
        created_by: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Create and submit a new claim.

        Normal frontend should not send employee snapshot, claim type snapshot,
        or policy snapshot. This service builds those from trusted DB data.

        Auto approval is intentionally disabled.
        """
        try:
            company_id = self._normalize_company_id(company_id)

            employee, employee_error = await self._get_employee_or_error(employee_id)
            if employee_error:
                return False, employee_error

            claim_type, claim_type_error = await self._get_claim_type_or_error(
                request.claim_type_id
            )
            if claim_type_error:
                return False, claim_type_error

            employee_snapshot = self._build_employee_snapshot(employee)
            claim_type_snapshot = self._build_claim_type_snapshot(claim_type)

            employee_snapshot["employee_id"] = employee_id

            company_policy = await self._get_company_claim_policy(company_id)

            policy_snapshot = self._build_policy_snapshot(
                claim_type=claim_type,
                company_policy=company_policy,
                currency=request.currency,
            )

            duplicate_error = await self._check_duplicate(
                employee_id=employee_id,
                claim_type_id=claim_type_snapshot["claim_type_id"],
                amount=request.amount,
                expense_date=request.expense_date,
                company_id=company_id,
            )

            if duplicate_error:
                return False, duplicate_error

            limit_check = await self._check_claim_limit(
                employee_id=employee_id,
                claim_type=claim_type,
                policy_snapshot=policy_snapshot,
                amount=request.amount,
                company_id=company_id,
            )

            if not limit_check.get("can_claim", False):
                return False, self._error(
                    "CLAIM_LIMIT_EXCEEDED",
                    limit_check.get("message", "Claim limit exceeded"),
                    details=limit_check,
                )

            bill_error = self._check_bill_requirement(
                amount=request.amount,
                attachments_count=len(request.attachments or []),
                policy_snapshot=policy_snapshot,
            )

            if bill_error:
                return False, bill_error

            attachments: List[Dict[str, Any]] = []

            for item in request.attachments or []:
                attachment = ClaimAttachment(
                    **item.model_dump(),
                    uploaded_by=employee_id,
                    uploaded_at=DateTime.utcnow(),
                )
                attachments.append(attachment.model_dump())

            approval_steps = self._build_approval_steps(
                amount=request.amount,
                employee_snapshot=employee_snapshot,
                policy_snapshot=policy_snapshot,
            )

            (
                status,
                requires_approval,
                current_approval_role,
                approved_amount,
                approved_at,
                approved_by,
            ) = self._determine_initial_status_and_approval(
                amount=request.amount,
                policy_snapshot=policy_snapshot,
                approval_steps=approval_steps,
                is_draft=False,
            )

            claim_id = await self._generate_claim_id(company_id)
            now = DateTime.utcnow()

            claim_data = {
                "claim_id": claim_id,
                "company_id": company_id,
                "source": ClaimSource.LOCAL.value,
                "external_hrms_id": None,
                "is_read_only": False,
                **employee_snapshot,
                **claim_type_snapshot,
                "policy_snapshot": policy_snapshot.model_dump(),
                "title": request.title,
                "description": request.description,
                "amount": request.amount,
                "currency": request.currency,
                "expense_date": request.expense_date,
                "vendor_name": request.vendor_name,
                "bill_number": request.bill_number,
                "project_code": request.project_code,
                "cost_center": request.cost_center,
                "attachments": attachments,
                "status": status.value,
                "priority": request.priority.value,
                "submitted_at": now,
                "resubmitted_at": None,
                "sent_back_at": None,
                "sent_back_reason": None,
                "approval_steps": [
                    step.model_dump() for step in approval_steps
                ],
                "action_history": [
                    self._build_action_event(
                        action=ClaimActionType.SUBMITTED,
                        actor_id=created_by or employee_id,
                        actor_role="employee",
                        new_status=status,
                        amount=request.amount,
                    )
                ],
                "requires_approval": requires_approval,
                "current_approval_role": (
                    current_approval_role.value if current_approval_role else None
                ),
                "approved_amount": approved_amount,
                "approved_at": approved_at,
                "approved_by": approved_by,
                "rejected_at": None,
                "rejected_by": None,
                "rejection_reason": None,
                "cancelled_at": None,
                "cancelled_by": None,
                "cancellation_reason": None,
                "withdrawn_at": None,
                "withdrawn_by": None,
                "withdrawal_reason": None,
                "payment_status": ClaimPaymentStatus.NOT_STARTED.value,
                "payment_reference": None,
                "payment_date": None,
                "payment_failure_reason": None,
                "paid_amount": None,
                "synced_to_hrms": False,
                "synced_at": None,
                "sync_error": None,
                "employee_notes": request.employee_notes,
                "internal_notes": None,
                "tags": request.tags or [],
                "extra_metadata": {
                    "limit_check": limit_check,
                    "auto_approval_disabled": True,
                },
                "created_by": created_by or employee_id,
                "updated_by": created_by or employee_id,
                "created_at": now,
                "updated_at": now,
            }

            validated = Claim(**claim_data)
            await self.claim_repo.create(validated.model_dump())

            created_claim = await self.claim_repo.find_by_claim_id(
                claim_id=claim_id,
                company_id=company_id,
            )

            return True, self._success(
                data={
                    "claim_id": claim_id,
                    "claim": self._to_claim_response(created_claim),
                },
                message="Claim submitted for approval successfully",
            )

        except ValidationError as exc:
            return False, self._error(
                "CLAIM_VALIDATION_FAILED",
                "Claim validation failed",
                details=exc.errors(),
            )

        except Exception as exc:
            return False, self._error(
                "CLAIM_CREATION_FAILED",
                f"Failed to create claim: {str(exc)}",
            )

    async def create_draft_claim(
        self,
        employee_id: str,
        request: CreateClaimDraftRequest,
        company_id: str = "default",
        created_by: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Create a draft claim.

        Draft needs enough valid fields to satisfy the document model.
        If optional data is missing, safe placeholder values are used.
        """
        try:
            company_id = self._normalize_company_id(company_id)

            employee, employee_error = await self._get_employee_or_error(employee_id)
            if employee_error:
                return False, employee_error

            employee_snapshot = self._build_employee_snapshot(employee)
            employee_snapshot["employee_id"] = employee_id

            if request.claim_type_id:
                claim_type, claim_type_error = await self._get_claim_type_or_error(
                    request.claim_type_id
                )
                if claim_type_error:
                    return False, claim_type_error

                claim_type_snapshot = self._build_claim_type_snapshot(claim_type)
            else:
                claim_type = {}
                claim_type_snapshot = {
                    "claim_type_id": "draft",
                    "claim_type_code": "DRAFT",
                    "claim_type_name": "Draft Claim",
                }

            company_policy = await self._get_company_claim_policy(company_id)

            policy_snapshot = self._build_policy_snapshot(
                claim_type=claim_type,
                company_policy=company_policy,
                currency=request.currency,
            )

            claim_id = await self._generate_claim_id(company_id)
            now = DateTime.utcnow()

            claim_data = {
                "claim_id": claim_id,
                "company_id": company_id,
                "source": ClaimSource.LOCAL.value,
                "external_hrms_id": None,
                "is_read_only": False,
                **employee_snapshot,
                **claim_type_snapshot,
                "policy_snapshot": policy_snapshot.model_dump(),
                "title": request.title or "Draft Claim",
                "description": request.description,
                "amount": request.amount or 1.0,
                "currency": request.currency,
                "expense_date": request.expense_date or Date.today(),
                "vendor_name": request.vendor_name,
                "bill_number": request.bill_number,
                "project_code": request.project_code,
                "cost_center": request.cost_center,
                "attachments": [],
                "status": ClaimStatus.DRAFT.value,
                "priority": request.priority.value,
                "submitted_at": None,
                "resubmitted_at": None,
                "sent_back_at": None,
                "sent_back_reason": None,
                "approval_steps": [],
                "action_history": [
                    self._build_action_event(
                        action=ClaimActionType.CREATED,
                        actor_id=created_by or employee_id,
                        actor_role="employee",
                        new_status=ClaimStatus.DRAFT,
                    )
                ],
                "requires_approval": True,
                "current_approval_role": None,
                "approved_amount": None,
                "approved_at": None,
                "approved_by": None,
                "rejected_at": None,
                "rejected_by": None,
                "rejection_reason": None,
                "cancelled_at": None,
                "cancelled_by": None,
                "cancellation_reason": None,
                "withdrawn_at": None,
                "withdrawn_by": None,
                "withdrawal_reason": None,
                "payment_status": ClaimPaymentStatus.NOT_STARTED.value,
                "payment_reference": None,
                "payment_date": None,
                "payment_failure_reason": None,
                "paid_amount": None,
                "synced_to_hrms": False,
                "synced_at": None,
                "sync_error": None,
                "employee_notes": request.employee_notes,
                "internal_notes": None,
                "tags": request.tags or [],
                "extra_metadata": {
                    "is_draft_placeholder_amount": request.amount is None,
                    "auto_approval_disabled": True,
                },
                "created_by": created_by or employee_id,
                "updated_by": created_by or employee_id,
                "created_at": now,
                "updated_at": now,
            }

            validated = Claim(**claim_data)
            await self.claim_repo.create(validated.model_dump())

            created_claim = await self.claim_repo.find_by_claim_id(
                claim_id=claim_id,
                company_id=company_id,
            )

            return True, self._success(
                data={
                    "claim_id": claim_id,
                    "claim": self._to_claim_response(created_claim),
                },
                message="Claim draft created successfully",
            )

        except ValidationError as exc:
            return False, self._error(
                "DRAFT_VALIDATION_FAILED",
                "Draft claim validation failed",
                details=exc.errors(),
            )

        except Exception as exc:
            return False, self._error(
                "DRAFT_CREATION_FAILED",
                f"Failed to create draft claim: {str(exc)}",
            )

    async def import_claim_from_hrms(
        self,
        request: ImportClaimFromHRMSRequest,
        imported_by: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Import a read-only claim from external HRMS.

        This is not for normal employee claim creation.
        """
        try:
            company_id = self._normalize_company_id(request.company_id)

            exists = await self.claim_repo.external_hrms_id_exists(
                external_hrms_id=request.external_hrms_id,
                company_id=company_id,
            )

            if exists:
                return False, self._error(
                    "HRMS_CLAIM_ALREADY_EXISTS",
                    "A claim with this external_hrms_id already exists",
                )

            claim_id = request.claim_id or await self._generate_claim_id(company_id)
            now = DateTime.utcnow()

            company_policy = await self._get_company_claim_policy(company_id)

            policy_snapshot = ClaimPolicySnapshot(
                requires_bill=False,
                requires_approval=True,
                auto_approve_below=company_policy.get("auto_approval_threshold"),
                allowed_currency=request.currency,
                allowed_file_types=company_policy.get(
                    "allowed_bill_formats",
                    ["pdf", "jpg", "jpeg", "png", "doc", "docx"],
                ),
            )

            attachments = []

            for item in request.attachments or []:
                attachments.append(
                    ClaimAttachment(
                        **item.model_dump(),
                        uploaded_by=imported_by,
                        uploaded_at=now,
                    ).model_dump()
                )

            claim_data = {
                "claim_id": claim_id,
                "company_id": company_id,
                "source": ClaimSource.HRMS.value,
                "external_hrms_id": request.external_hrms_id,
                "is_read_only": True,
                "employee_id": request.employee_id,
                "employee_code": request.employee_code,
                "employee_name": request.employee_name,
                "department_id": request.department_id,
                "department_name": request.department_name,
                "manager_id": request.manager_id,
                "manager_name": request.manager_name,
                "claim_type_id": request.claim_type_id,
                "claim_type_code": request.claim_type_code,
                "claim_type_name": request.claim_type_name,
                "policy_snapshot": policy_snapshot.model_dump(),
                "title": request.title,
                "description": request.description,
                "amount": request.amount,
                "currency": request.currency,
                "expense_date": request.expense_date,
                "vendor_name": None,
                "bill_number": None,
                "project_code": None,
                "cost_center": None,
                "attachments": attachments,
                "status": request.status.value,
                "priority": request.priority.value,
                "submitted_at": now,
                "resubmitted_at": None,
                "sent_back_at": None,
                "sent_back_reason": None,
                "approval_steps": [],
                "action_history": [
                    self._build_action_event(
                        action=ClaimActionType.IMPORTED_FROM_HRMS,
                        actor_id=imported_by,
                        actor_role="system",
                        new_status=request.status,
                    )
                ],
                "requires_approval": True,
                "current_approval_role": None,
                "approved_amount": request.approved_amount,
                "approved_at": None,
                "approved_by": None,
                "rejected_at": None,
                "rejected_by": None,
                "rejection_reason": None,
                "cancelled_at": None,
                "cancelled_by": None,
                "cancellation_reason": None,
                "withdrawn_at": None,
                "withdrawn_by": None,
                "withdrawal_reason": None,
                "payment_status": request.payment_status.value,
                "payment_reference": request.payment_reference,
                "payment_date": request.payment_date,
                "payment_failure_reason": None,
                "paid_amount": request.paid_amount,
                "synced_to_hrms": True,
                "synced_at": now,
                "sync_error": None,
                "employee_notes": None,
                "internal_notes": None,
                "tags": [],
                "extra_metadata": request.extra_metadata or {},
                "created_by": imported_by,
                "updated_by": imported_by,
                "created_at": now,
                "updated_at": now,
            }

            validated = Claim(**claim_data)
            await self.claim_repo.create(validated.model_dump())

            created_claim = await self.claim_repo.find_by_claim_id(
                claim_id=claim_id,
                company_id=company_id,
            )

            return True, self._success(
                data={
                    "claim_id": claim_id,
                    "external_hrms_id": request.external_hrms_id,
                    "is_read_only": True,
                    "claim": self._to_private_response(created_claim),
                },
                message="Claim imported from HRMS successfully",
            )

        except ValidationError as exc:
            return False, self._error(
                "HRMS_IMPORT_VALIDATION_FAILED",
                "HRMS claim validation failed",
                details=exc.errors(),
            )

        except Exception as exc:
            return False, self._error(
                "HRMS_IMPORT_FAILED",
                f"Failed to import HRMS claim: {str(exc)}",
            )

    # ---------------------------------------------------------------------
    # Read operations
    # ---------------------------------------------------------------------

    async def get_claim_by_id(
        self,
        claim_id: str,
        requesting_employee_id: Optional[str] = None,
        is_manager: bool = False,
        is_hr: bool = False,
        is_admin: bool = False,
        is_finance: bool = False,
        company_id: str = "default",
        private: bool = False,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Get claim by ID with basic access control.

        Route-level RBAC should still be enforced separately.
        """
        try:
            company_id = self._normalize_company_id(company_id)

            claim, error = await self._get_claim_or_error(claim_id, company_id)
            if error:
                return False, error

            has_elevated_access = is_hr or is_admin or is_finance

            if not has_elevated_access:
                if (
                    requesting_employee_id
                    and claim.get("employee_id") == requesting_employee_id
                ):
                    pass
                elif (
                    is_manager
                    and requesting_employee_id
                    and claim.get("manager_id") == requesting_employee_id
                ):
                    pass
                else:
                    return False, self._error(
                        "ACCESS_DENIED",
                        "You do not have permission to view this claim",
                    )

            response_claim = (
                self._to_private_response(claim)
                if private or has_elevated_access
                else self._to_claim_response(claim)
            )

            return True, self._success(
                data={"claim": response_claim},
                message="Claim retrieved successfully",
            )

        except Exception as exc:
            return False, self._error(
                "CLAIM_RETRIEVAL_FAILED",
                f"Failed to retrieve claim: {str(exc)}",
            )

    async def list_my_claims(
        self,
        employee_id: str,
        filters: ClaimListFilters,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        List claims for current employee.
        """
        try:
            company_id = self._normalize_company_id(filters.company_id)
            skip = (filters.page - 1) * filters.page_size

            claims = await self.claim_repo.list_claims(
                company_id=company_id,
                status=filters.status,
                source=filters.source,
                claim_type_id=filters.claim_type_id,
                claim_type_code=filters.claim_type_code,
                employee_id=employee_id,
                priority=filters.priority,
                payment_status=filters.payment_status,
                is_read_only=filters.is_read_only,
                from_date=filters.from_date,
                to_date=filters.to_date,
                min_amount=filters.min_amount,
                max_amount=filters.max_amount,
                search=filters.search,
                skip=skip,
                limit=filters.page_size,
                sort_by=filters.sort_by,
                sort_order=filters.sort_order,
            )

            total = await self.claim_repo.count_claims(
                company_id=company_id,
                status=filters.status,
                source=filters.source,
                claim_type_id=filters.claim_type_id,
                claim_type_code=filters.claim_type_code,
                employee_id=employee_id,
                priority=filters.priority,
                payment_status=filters.payment_status,
                is_read_only=filters.is_read_only,
                from_date=filters.from_date,
                to_date=filters.to_date,
                min_amount=filters.min_amount,
                max_amount=filters.max_amount,
                search=filters.search,
            )

            return True, self._success(
                data={
                    "items": [self._to_summary(claim) for claim in claims],
                    "total": total,
                    "page": filters.page,
                    "page_size": filters.page_size,
                    "total_pages": ceil(total / filters.page_size) if total else 0,
                },
                message=f"Retrieved {len(claims)} claims",
            )

        except Exception as exc:
            return False, self._error(
                "CLAIM_LIST_FAILED",
                f"Failed to retrieve claims: {str(exc)}",
            )

    async def list_all_claims(
        self,
        filters: ClaimListFilters,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        HR/Admin/Finance list endpoint.
        """
        try:
            company_id = self._normalize_company_id(filters.company_id)
            skip = (filters.page - 1) * filters.page_size

            claims = await self.claim_repo.list_claims(
                company_id=company_id,
                status=filters.status,
                source=filters.source,
                claim_type_id=filters.claim_type_id,
                claim_type_code=filters.claim_type_code,
                employee_id=filters.employee_id,
                employee_code=filters.employee_code,
                department_id=filters.department_id,
                manager_id=filters.manager_id,
                priority=filters.priority,
                payment_status=filters.payment_status,
                is_read_only=filters.is_read_only,
                from_date=filters.from_date,
                to_date=filters.to_date,
                min_amount=filters.min_amount,
                max_amount=filters.max_amount,
                search=filters.search,
                skip=skip,
                limit=filters.page_size,
                sort_by=filters.sort_by,
                sort_order=filters.sort_order,
            )

            total = await self.claim_repo.count_claims(
                company_id=company_id,
                status=filters.status,
                source=filters.source,
                claim_type_id=filters.claim_type_id,
                claim_type_code=filters.claim_type_code,
                employee_id=filters.employee_id,
                employee_code=filters.employee_code,
                department_id=filters.department_id,
                manager_id=filters.manager_id,
                priority=filters.priority,
                payment_status=filters.payment_status,
                is_read_only=filters.is_read_only,
                from_date=filters.from_date,
                to_date=filters.to_date,
                min_amount=filters.min_amount,
                max_amount=filters.max_amount,
                search=filters.search,
            )

            return True, self._success(
                data={
                    "items": [self._to_summary(claim) for claim in claims],
                    "total": total,
                    "page": filters.page,
                    "page_size": filters.page_size,
                    "total_pages": ceil(total / filters.page_size) if total else 0,
                },
                message=f"Retrieved {len(claims)} claims",
            )

        except Exception as exc:
            return False, self._error(
                "CLAIM_LIST_FAILED",
                f"Failed to retrieve claims: {str(exc)}",
            )

    async def get_pending_approvals(
        self,
        filters: PendingApprovalsFilters,
        approver_id: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Get claims pending approval for manager/finance/HR/admin.
        """
        try:
            company_id = self._normalize_company_id(filters.company_id)
            skip = (filters.page - 1) * filters.page_size

            claims = await self.claim_repo.find_pending_approvals(
                company_id=company_id,
                approver_role=filters.approver_role,
                approver_id=approver_id,
                claim_type_id=filters.claim_type_id,
                department_id=filters.department_id,
                priority=filters.priority,
                min_amount=filters.min_amount,
                max_amount=filters.max_amount,
                skip=skip,
                limit=filters.page_size,
            )

            total = await self.claim_repo.count_pending_approvals(
                company_id=company_id,
                approver_role=filters.approver_role,
                approver_id=approver_id,
                claim_type_id=filters.claim_type_id,
                department_id=filters.department_id,
                priority=filters.priority,
                min_amount=filters.min_amount,
                max_amount=filters.max_amount,
            )

            return True, self._success(
                data={
                    "items": [self._to_summary(claim) for claim in claims],
                    "total": total,
                    "page": filters.page,
                    "page_size": filters.page_size,
                    "total_pages": ceil(total / filters.page_size) if total else 0,
                },
                message=f"Retrieved {len(claims)} pending approvals",
            )

        except Exception as exc:
            return False, self._error(
                "PENDING_APPROVALS_FAILED",
                f"Failed to retrieve pending approvals: {str(exc)}",
            )

    # ---------------------------------------------------------------------
    # Update / submit operations
    # ---------------------------------------------------------------------

    async def update_claim(
        self,
        claim_id: str,
        employee_id: str,
        request: UpdateClaimRequest,
        company_id: str = "default",
        updated_by: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Update editable claim fields.
        """
        try:
            company_id = self._normalize_company_id(company_id)

            claim, error = await self._get_claim_or_error(claim_id, company_id)
            if error:
                return False, error

            read_only_error = self._ensure_not_read_only(claim)
            if read_only_error:
                return False, read_only_error

            owner_error = self._ensure_owner(claim, employee_id)
            if owner_error:
                return False, owner_error

            if claim.get("status") not in self.EDITABLE_STATUSES:
                return False, self._error(
                    "CLAIM_NOT_EDITABLE",
                    "Only draft or sent-back claims can be updated",
                )

            update_data = request.model_dump(exclude_unset=True, exclude_none=True)

            if not update_data:
                return False, self._error(
                    "NO_UPDATE_FIELDS",
                    "No fields provided for update",
                )

            new_amount = update_data.get("amount", claim.get("amount"))
            new_expense_date = update_data.get("expense_date", claim.get("expense_date"))
            new_claim_type_id = update_data.get(
                "claim_type_id",
                claim.get("claim_type_id"),
            )

            if (
                "amount" in update_data
                or "expense_date" in update_data
                or "claim_type_id" in update_data
            ):
                duplicate_error = await self._check_duplicate(
                    employee_id=employee_id,
                    claim_type_id=new_claim_type_id,
                    amount=new_amount,
                    expense_date=new_expense_date,
                    company_id=company_id,
                    exclude_claim_id=claim_id,
                )

                if duplicate_error:
                    return False, duplicate_error

                claim_type, claim_type_error = await self._get_claim_type_or_error(
                    new_claim_type_id
                )
                if claim_type_error:
                    return False, claim_type_error

                company_policy = await self._get_company_claim_policy(company_id)

                policy_snapshot = self._build_policy_snapshot(
                    claim_type=claim_type,
                    company_policy=company_policy,
                    currency=update_data.get("currency", claim.get("currency", "INR")),
                )

                limit_check = await self._check_claim_limit(
                    employee_id=employee_id,
                    claim_type=claim_type,
                    policy_snapshot=policy_snapshot,
                    amount=new_amount,
                    company_id=company_id,
                )

                if not limit_check.get("can_claim", False):
                    return False, self._error(
                        "CLAIM_LIMIT_EXCEEDED",
                        limit_check.get("message", "Claim limit exceeded"),
                        details=limit_check,
                    )

                update_data["policy_snapshot"] = policy_snapshot.model_dump()
                update_data.update(self._build_claim_type_snapshot(claim_type))

            update_data["updated_by"] = updated_by or employee_id

            success = await self.claim_repo.update(
                claim_id=claim_id,
                company_id=company_id,
                update_data=update_data,
            )

            if not success:
                return False, self._error(
                    "CLAIM_UPDATE_FAILED",
                    "Failed to update claim",
                )

            await self.claim_repo.add_action_history(
                claim_id=claim_id,
                company_id=company_id,
                action_event=self._build_action_event(
                    action=ClaimActionType.UPDATED,
                    actor_id=updated_by or employee_id,
                    actor_role="employee",
                    old_status=ClaimStatus(claim["status"]),
                    new_status=ClaimStatus(claim["status"]),
                    comments="Claim updated",
                ),
            )

            updated_claim = await self.claim_repo.find_by_claim_id(
                claim_id=claim_id,
                company_id=company_id,
            )

            return True, self._success(
                data={"claim": self._to_claim_response(updated_claim)},
                message="Claim updated successfully",
            )

        except Exception as exc:
            return False, self._error(
                "CLAIM_UPDATE_FAILED",
                f"Failed to update claim: {str(exc)}",
            )

    async def submit_claim(
        self,
        claim_id: str,
        employee_id: str,
        request: SubmitClaimRequest,
        company_id: str = "default",
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Submit a draft/sent-back claim.

        Auto approval is intentionally disabled.
        """
        try:
            company_id = self._normalize_company_id(company_id)

            claim, error = await self._get_claim_or_error(claim_id, company_id)
            if error:
                return False, error

            read_only_error = self._ensure_not_read_only(claim)
            if read_only_error:
                return False, read_only_error

            owner_error = self._ensure_owner(claim, employee_id)
            if owner_error:
                return False, owner_error

            if claim.get("status") not in self.SUBMITTABLE_STATUSES:
                return False, self._error(
                    "CLAIM_NOT_SUBMITTABLE",
                    "Only draft or sent-back claims can be submitted",
                )

            policy_snapshot = ClaimPolicySnapshot(**claim["policy_snapshot"])

            bill_error = self._check_bill_requirement(
                amount=claim["amount"],
                attachments_count=len(claim.get("attachments") or []),
                policy_snapshot=policy_snapshot,
            )
            if bill_error:
                return False, bill_error

            claim_type, claim_type_error = await self._get_claim_type_or_error(
                claim["claim_type_id"]
            )
            if claim_type_error:
                return False, claim_type_error

            limit_check = await self._check_claim_limit(
                employee_id=employee_id,
                claim_type=claim_type,
                policy_snapshot=policy_snapshot,
                amount=claim["amount"],
                company_id=company_id,
            )

            if not limit_check.get("can_claim", False):
                return False, self._error(
                    "CLAIM_LIMIT_EXCEEDED",
                    limit_check.get("message", "Claim limit exceeded"),
                    details=limit_check,
                )

            employee_snapshot = {
                "manager_id": claim.get("manager_id"),
                "manager_name": claim.get("manager_name"),
            }

            approval_steps = self._build_approval_steps(
                amount=claim["amount"],
                employee_snapshot=employee_snapshot,
                policy_snapshot=policy_snapshot,
            )

            (
                status,
                requires_approval,
                current_approval_role,
                approved_amount,
                approved_at,
                approved_by,
            ) = self._determine_initial_status_and_approval(
                amount=claim["amount"],
                policy_snapshot=policy_snapshot,
                approval_steps=approval_steps,
                is_draft=False,
            )

            update_data = {
                "status": status.value,
                "submitted_at": DateTime.utcnow(),
                "approval_steps": [step.model_dump() for step in approval_steps],
                "requires_approval": requires_approval,
                "current_approval_role": (
                    current_approval_role.value if current_approval_role else None
                ),
                "approved_amount": approved_amount,
                "approved_at": approved_at,
                "approved_by": approved_by,
                "updated_by": employee_id,
                "extra_metadata.limit_check": limit_check,
                "extra_metadata.auto_approval_disabled": True,
            }

            success = await self.claim_repo.update(
                claim_id=claim_id,
                company_id=company_id,
                update_data=update_data,
            )

            if not success:
                return False, self._error(
                    "CLAIM_SUBMIT_FAILED",
                    "Failed to submit claim",
                )

            await self.claim_repo.add_action_history(
                claim_id=claim_id,
                company_id=company_id,
                action_event=self._build_action_event(
                    action=ClaimActionType.SUBMITTED,
                    actor_id=employee_id,
                    actor_role="employee",
                    old_status=ClaimStatus(claim["status"]),
                    new_status=status,
                    amount=claim["amount"],
                ),
            )

            updated_claim = await self.claim_repo.find_by_claim_id(
                claim_id=claim_id,
                company_id=company_id,
            )

            return True, self._success(
                data={
                    "claim_id": claim_id,
                    "status": status.value,
                    "claim": self._to_claim_response(updated_claim),
                },
                message="Claim submitted for approval successfully",
            )

        except Exception as exc:
            return False, self._error(
                "CLAIM_SUBMIT_FAILED",
                f"Failed to submit claim: {str(exc)}",
            )

    async def resubmit_claim(
        self,
        claim_id: str,
        employee_id: str,
        request: ResubmitClaimRequest,
        company_id: str = "default",
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Resubmit a sent-back claim.
        """
        try:
            company_id = self._normalize_company_id(company_id)

            claim, error = await self._get_claim_or_error(claim_id, company_id)
            if error:
                return False, error

            read_only_error = self._ensure_not_read_only(claim)
            if read_only_error:
                return False, read_only_error

            owner_error = self._ensure_owner(claim, employee_id)
            if owner_error:
                return False, owner_error

            if claim.get("status") != ClaimStatus.SENT_BACK.value:
                return False, self._error(
                    "CLAIM_NOT_SENT_BACK",
                    "Only sent-back claims can be resubmitted",
                )

            success = await self.claim_repo.resubmit_claim(
                claim_id=claim_id,
                company_id=company_id,
            )

            if not success:
                return False, self._error(
                    "CLAIM_RESUBMIT_FAILED",
                    "Failed to resubmit claim",
                )

            await self.claim_repo.add_action_history(
                claim_id=claim_id,
                company_id=company_id,
                action_event=self._build_action_event(
                    action=ClaimActionType.RESUBMITTED,
                    actor_id=employee_id,
                    actor_role="employee",
                    old_status=ClaimStatus.SENT_BACK,
                    new_status=ClaimStatus.RESUBMITTED,
                    comments=request.comments,
                ),
            )

            updated_claim = await self.claim_repo.find_by_claim_id(
                claim_id=claim_id,
                company_id=company_id,
            )

            return True, self._success(
                data={"claim": self._to_claim_response(updated_claim)},
                message="Claim resubmitted successfully",
            )

        except Exception as exc:
            return False, self._error(
                "CLAIM_RESUBMIT_FAILED",
                f"Failed to resubmit claim: {str(exc)}",
            )

    # ---------------------------------------------------------------------
    # Approval operations
    # ---------------------------------------------------------------------

    def _find_pending_step(
        self,
        claim: Dict[str, Any],
        approver_role: Optional[ClaimApproverRole] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Find first pending approval step, optionally by role.
        """
        for step in claim.get("approval_steps") or []:
            if step.get("approval_status") != ClaimApprovalStatus.PENDING.value:
                continue

            if approver_role and step.get("approver_role") != approver_role.value:
                continue

            return step

        return None

    def _next_pending_role_after_step(
        self,
        claim: Dict[str, Any],
        current_step_order: int,
    ) -> Optional[ClaimApproverRole]:
        """
        Find next pending approval role after current step.
        """
        steps = sorted(
            claim.get("approval_steps") or [],
            key=lambda item: item.get("step_order", 0),
        )

        for step in steps:
            if step.get("step_order", 0) <= current_step_order:
                continue

            if step.get("approval_status") == ClaimApprovalStatus.PENDING.value:
                return ClaimApproverRole(step["approver_role"])

        return None

    async def approve_claim(
        self,
        claim_id: str,
        approver_id: str,
        request: ApproveClaimRequest,
        company_id: str = "default",
        approver_name: Optional[str] = None,
        approver_role: Optional[ClaimApproverRole] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Approve current pending approval step.

        Only human approvers should call this through protected routes.
        """
        try:
            company_id = self._normalize_company_id(company_id)

            claim, error = await self._get_claim_or_error(claim_id, company_id)
            if error:
                return False, error

            read_only_error = self._ensure_not_read_only(claim)
            if read_only_error:
                return False, read_only_error

            if claim.get("status") not in self.APPROVABLE_STATUSES:
                return False, self._error(
                    "CLAIM_NOT_APPROVABLE",
                    f"Claim is {claim.get('status')}, not approvable",
                )

            step = self._find_pending_step(claim, approver_role=approver_role)

            if not step:
                return False, self._error(
                    "NO_PENDING_APPROVAL_STEP",
                    "No pending approval step found for this claim",
                )

            approved_amount = request.approved_amount or claim["amount"]

            if approved_amount > claim["amount"]:
                return False, self._error(
                    "INVALID_APPROVED_AMOUNT",
                    "Approved amount cannot exceed requested amount",
                )

            step_order = int(step["step_order"])

            success = await self.claim_repo.approve_step(
                claim_id=claim_id,
                step_order=step_order,
                approver_id=approver_id,
                approver_name=approver_name,
                comments=request.comments,
                company_id=company_id,
            )

            if not success:
                return False, self._error(
                    "APPROVAL_STEP_UPDATE_FAILED",
                    "Failed to update approval step",
                )

            updated_claim = await self.claim_repo.find_by_claim_id(
                claim_id=claim_id,
                company_id=company_id,
            )

            next_role = self._next_pending_role_after_step(updated_claim, step_order)

            if next_role:
                new_status = (
                    ClaimStatus.MANAGER_APPROVED
                    if step.get("approver_role") == ClaimApproverRole.MANAGER.value
                    else ClaimStatus.FINANCE_APPROVED
                )

                await self.claim_repo.update_status(
                    claim_id=claim_id,
                    company_id=company_id,
                    new_status=new_status,
                    extra_updates={
                        "approved_amount": approved_amount,
                        "current_approval_role": next_role.value,
                        "updated_by": approver_id,
                    },
                )

            else:
                new_status = ClaimStatus.APPROVED

                await self.claim_repo.approve_claim_final(
                    claim_id=claim_id,
                    company_id=company_id,
                    approved_by=approver_id,
                    approved_amount=approved_amount,
                )

                await self.claim_repo.update(
                    claim_id=claim_id,
                    company_id=company_id,
                    update_data={
                        "current_approval_role": None,
                        "updated_by": approver_id,
                    },
                )

            await self.claim_repo.add_action_history(
                claim_id=claim_id,
                company_id=company_id,
                action_event=self._build_action_event(
                    action=(
                        ClaimActionType.MANAGER_APPROVED
                        if step.get("approver_role") == ClaimApproverRole.MANAGER.value
                        else ClaimActionType.FINANCE_APPROVED
                    ),
                    actor_id=approver_id,
                    actor_name=approver_name,
                    actor_role=step.get("approver_role"),
                    old_status=ClaimStatus(claim["status"]),
                    new_status=new_status,
                    comments=request.comments,
                    amount=approved_amount,
                ),
            )

            final_claim = await self.claim_repo.find_by_claim_id(
                claim_id=claim_id,
                company_id=company_id,
            )

            return True, self._success(
                data={"claim": self._to_private_response(final_claim)},
                message="Claim approved successfully",
            )

        except Exception as exc:
            return False, self._error(
                "CLAIM_APPROVAL_FAILED",
                f"Failed to approve claim: {str(exc)}",
            )

    async def reject_claim(
        self,
        claim_id: str,
        approver_id: str,
        request: RejectClaimRequest,
        company_id: str = "default",
        approver_name: Optional[str] = None,
        approver_role: Optional[ClaimApproverRole] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Reject claim.
        """
        try:
            company_id = self._normalize_company_id(company_id)

            claim, error = await self._get_claim_or_error(claim_id, company_id)
            if error:
                return False, error

            read_only_error = self._ensure_not_read_only(claim)
            if read_only_error:
                return False, read_only_error

            if claim.get("status") not in self.APPROVABLE_STATUSES:
                return False, self._error(
                    "CLAIM_NOT_REJECTABLE",
                    f"Claim is {claim.get('status')}, not rejectable",
                )

            step = self._find_pending_step(claim, approver_role=approver_role)

            if step:
                await self.claim_repo.reject_step(
                    claim_id=claim_id,
                    step_order=int(step["step_order"]),
                    approver_id=approver_id,
                    approver_name=approver_name,
                    rejection_reason=request.rejection_reason,
                    company_id=company_id,
                )

            success = await self.claim_repo.reject_claim(
                claim_id=claim_id,
                company_id=company_id,
                rejected_by=approver_id,
                rejection_reason=request.rejection_reason,
            )

            if not success:
                return False, self._error(
                    "CLAIM_REJECTION_FAILED",
                    "Failed to reject claim",
                )

            await self.claim_repo.add_action_history(
                claim_id=claim_id,
                company_id=company_id,
                action_event=self._build_action_event(
                    action=ClaimActionType.REJECTED,
                    actor_id=approver_id,
                    actor_name=approver_name,
                    actor_role=approver_role.value if approver_role else None,
                    old_status=ClaimStatus(claim["status"]),
                    new_status=ClaimStatus.REJECTED,
                    comments=request.rejection_reason,
                ),
            )

            updated_claim = await self.claim_repo.find_by_claim_id(
                claim_id=claim_id,
                company_id=company_id,
            )

            return True, self._success(
                data={"claim": self._to_private_response(updated_claim)},
                message="Claim rejected successfully",
            )

        except Exception as exc:
            return False, self._error(
                "CLAIM_REJECTION_FAILED",
                f"Failed to reject claim: {str(exc)}",
            )

    async def send_back_claim(
        self,
        claim_id: str,
        actor_id: str,
        request: SendBackClaimRequest,
        company_id: str = "default",
        actor_name: Optional[str] = None,
        actor_role: Optional[ClaimApproverRole] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Send claim back to employee for correction.
        """
        try:
            company_id = self._normalize_company_id(company_id)

            claim, error = await self._get_claim_or_error(claim_id, company_id)
            if error:
                return False, error

            read_only_error = self._ensure_not_read_only(claim)
            if read_only_error:
                return False, read_only_error

            if claim.get("status") not in self.APPROVABLE_STATUSES:
                return False, self._error(
                    "CLAIM_NOT_SEND_BACK_ALLOWED",
                    "Only pending approval claims can be sent back",
                )

            step = self._find_pending_step(claim, approver_role=actor_role)

            if step:
                await self.claim_repo.send_back_step(
                    claim_id=claim_id,
                    step_order=int(step["step_order"]),
                    approver_id=actor_id,
                    approver_name=actor_name,
                    sent_back_reason=request.sent_back_reason,
                    comments=request.comments,
                    company_id=company_id,
                )

            success = await self.claim_repo.send_back_claim(
                claim_id=claim_id,
                company_id=company_id,
                sent_back_reason=request.sent_back_reason,
            )

            if not success:
                return False, self._error(
                    "CLAIM_SEND_BACK_FAILED",
                    "Failed to send claim back",
                )

            await self.claim_repo.add_action_history(
                claim_id=claim_id,
                company_id=company_id,
                action_event=self._build_action_event(
                    action=ClaimActionType.SENT_BACK,
                    actor_id=actor_id,
                    actor_name=actor_name,
                    actor_role=actor_role.value if actor_role else None,
                    old_status=ClaimStatus(claim["status"]),
                    new_status=ClaimStatus.SENT_BACK,
                    comments=request.sent_back_reason,
                ),
            )

            updated_claim = await self.claim_repo.find_by_claim_id(
                claim_id=claim_id,
                company_id=company_id,
            )

            return True, self._success(
                data={"claim": self._to_private_response(updated_claim)},
                message="Claim sent back successfully",
            )

        except Exception as exc:
            return False, self._error(
                "CLAIM_SEND_BACK_FAILED",
                f"Failed to send claim back: {str(exc)}",
            )

    # ---------------------------------------------------------------------
    # Cancel / withdraw operations
    # ---------------------------------------------------------------------

    async def cancel_claim(
        self,
        claim_id: str,
        employee_id: str,
        request: CancelClaimRequest,
        company_id: str = "default",
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Employee cancels own claim.
        """
        try:
            company_id = self._normalize_company_id(company_id)

            claim, error = await self._get_claim_or_error(claim_id, company_id)
            if error:
                return False, error

            read_only_error = self._ensure_not_read_only(claim)
            if read_only_error:
                return False, read_only_error

            owner_error = self._ensure_owner(claim, employee_id)
            if owner_error:
                return False, owner_error

            if claim.get("status") not in self.CANCELLABLE_STATUSES:
                return False, self._error(
                    "CLAIM_NOT_CANCELLABLE",
                    f"Cannot cancel claim with status {claim.get('status')}",
                )

            success = await self.claim_repo.cancel_claim(
                claim_id=claim_id,
                company_id=company_id,
                cancellation_reason=request.cancellation_reason,
                cancelled_by=employee_id,
            )

            if not success:
                return False, self._error(
                    "CLAIM_CANCEL_FAILED",
                    "Failed to cancel claim",
                )

            await self.claim_repo.add_action_history(
                claim_id=claim_id,
                company_id=company_id,
                action_event=self._build_action_event(
                    action=ClaimActionType.CANCELLED,
                    actor_id=employee_id,
                    actor_role="employee",
                    old_status=ClaimStatus(claim["status"]),
                    new_status=ClaimStatus.CANCELLED,
                    comments=request.cancellation_reason,
                ),
            )

            updated_claim = await self.claim_repo.find_by_claim_id(
                claim_id=claim_id,
                company_id=company_id,
            )

            return True, self._success(
                data={"claim": self._to_claim_response(updated_claim)},
                message="Claim cancelled successfully",
            )

        except Exception as exc:
            return False, self._error(
                "CLAIM_CANCEL_FAILED",
                f"Failed to cancel claim: {str(exc)}",
            )

    async def withdraw_claim(
        self,
        claim_id: str,
        employee_id: str,
        request: WithdrawClaimRequest,
        company_id: str = "default",
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Employee withdraws own claim.
        """
        try:
            company_id = self._normalize_company_id(company_id)

            claim, error = await self._get_claim_or_error(claim_id, company_id)
            if error:
                return False, error

            read_only_error = self._ensure_not_read_only(claim)
            if read_only_error:
                return False, read_only_error

            owner_error = self._ensure_owner(claim, employee_id)
            if owner_error:
                return False, owner_error

            if claim.get("status") not in self.WITHDRAWABLE_STATUSES:
                return False, self._error(
                    "CLAIM_NOT_WITHDRAWABLE",
                    f"Cannot withdraw claim with status {claim.get('status')}",
                )

            success = await self.claim_repo.withdraw_claim(
                claim_id=claim_id,
                company_id=company_id,
                withdrawal_reason=request.withdrawal_reason,
                withdrawn_by=employee_id,
            )

            if not success:
                return False, self._error(
                    "CLAIM_WITHDRAW_FAILED",
                    "Failed to withdraw claim",
                )

            await self.claim_repo.add_action_history(
                claim_id=claim_id,
                company_id=company_id,
                action_event=self._build_action_event(
                    action=ClaimActionType.WITHDRAWN,
                    actor_id=employee_id,
                    actor_role="employee",
                    old_status=ClaimStatus(claim["status"]),
                    new_status=ClaimStatus.WITHDRAWN,
                    comments=request.withdrawal_reason,
                ),
            )

            updated_claim = await self.claim_repo.find_by_claim_id(
                claim_id=claim_id,
                company_id=company_id,
            )

            return True, self._success(
                data={"claim": self._to_claim_response(updated_claim)},
                message="Claim withdrawn successfully",
            )

        except Exception as exc:
            return False, self._error(
                "CLAIM_WITHDRAW_FAILED",
                f"Failed to withdraw claim: {str(exc)}",
            )

    # ---------------------------------------------------------------------
    # Attachment operations
    # ---------------------------------------------------------------------

    async def add_attachment(
        self,
        claim_id: str,
        employee_id: str,
        request: AddClaimAttachmentRequest,
        company_id: str = "default",
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Add attachment metadata to claim.
        """
        try:
            company_id = self._normalize_company_id(company_id)

            claim, error = await self._get_claim_or_error(claim_id, company_id)
            if error:
                return False, error

            read_only_error = self._ensure_not_read_only(claim)
            if read_only_error:
                return False, read_only_error

            owner_error = self._ensure_owner(claim, employee_id)
            if owner_error:
                return False, owner_error

            if claim.get("status") not in self.EDITABLE_STATUSES:
                return False, self._error(
                    "ATTACHMENT_NOT_ALLOWED",
                    "Attachments can be added only to draft or sent-back claims",
                )

            attachment = ClaimAttachment(
                **request.model_dump(),
                uploaded_by=employee_id,
                uploaded_at=DateTime.utcnow(),
            )

            success = await self.claim_repo.add_attachment(
                claim_id=claim_id,
                company_id=company_id,
                attachment=attachment.model_dump(),
            )

            if not success:
                return False, self._error(
                    "ATTACHMENT_ADD_FAILED",
                    "Failed to add attachment",
                )

            await self.claim_repo.add_action_history(
                claim_id=claim_id,
                company_id=company_id,
                action_event=self._build_action_event(
                    action=ClaimActionType.UPDATED,
                    actor_id=employee_id,
                    actor_role="employee",
                    comments=f"Attachment added: {attachment.file_name}",
                ),
            )

            return True, self._success(
                data={
                    "claim_id": claim_id,
                    "attachment": attachment.model_dump(),
                },
                message="Attachment added successfully",
            )

        except ValidationError as exc:
            return False, self._error(
                "ATTACHMENT_VALIDATION_FAILED",
                "Attachment validation failed",
                details=exc.errors(),
            )

        except Exception as exc:
            return False, self._error(
                "ATTACHMENT_ADD_FAILED",
                f"Failed to add attachment: {str(exc)}",
            )

    async def verify_attachment(
        self,
        claim_id: str,
        attachment_index: int,
        verifier_id: str,
        request: VerifyClaimAttachmentRequest,
        company_id: str = "default",
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Verify or unverify a claim attachment.
        """
        try:
            company_id = self._normalize_company_id(company_id)

            claim, error = await self._get_claim_or_error(claim_id, company_id)
            if error:
                return False, error

            read_only_error = self._ensure_not_read_only(claim)
            if read_only_error:
                return False, read_only_error

            success = await self.claim_repo.verify_attachment(
                claim_id=claim_id,
                company_id=company_id,
                attachment_index=attachment_index,
                verified_by=verifier_id,
                is_verified=request.is_verified,
            )

            if not success:
                return False, self._error(
                    "ATTACHMENT_VERIFY_FAILED",
                    "Failed to update attachment verification",
                )

            await self.claim_repo.add_action_history(
                claim_id=claim_id,
                company_id=company_id,
                action_event=self._build_action_event(
                    action=ClaimActionType.UPDATED,
                    actor_id=verifier_id,
                    actor_role="finance",
                    comments=request.comments or "Attachment verification updated",
                ),
            )

            return True, self._success(
                data={
                    "claim_id": claim_id,
                    "attachment_index": attachment_index,
                    "is_verified": request.is_verified,
                },
                message="Attachment verification updated successfully",
            )

        except Exception as exc:
            return False, self._error(
                "ATTACHMENT_VERIFY_FAILED",
                f"Failed to verify attachment: {str(exc)}",
            )

    # ---------------------------------------------------------------------
    # Payment operations
    # ---------------------------------------------------------------------

    async def start_payment_processing(
        self,
        claim_id: str,
        actor_id: str,
        request: Optional[StartClaimPaymentProcessingRequest] = None,
        company_id: str = "default",
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Mark approved claim as payment processing.
        """
        try:
            company_id = self._normalize_company_id(company_id)

            claim, error = await self._get_claim_or_error(claim_id, company_id)
            if error:
                return False, error

            read_only_error = self._ensure_not_read_only(claim)
            if read_only_error:
                return False, read_only_error

            if claim.get("status") != ClaimStatus.APPROVED.value:
                return False, self._error(
                    "CLAIM_NOT_APPROVED",
                    "Only approved claims can move to payment processing",
                )

            success = await self.claim_repo.start_payment_processing(
                claim_id=claim_id,
                company_id=company_id,
            )

            if not success:
                return False, self._error(
                    "PAYMENT_PROCESSING_FAILED",
                    "Failed to start payment processing",
                )

            await self.claim_repo.add_action_history(
                claim_id=claim_id,
                company_id=company_id,
                action_event=self._build_action_event(
                    action=ClaimActionType.PROCESSING_STARTED,
                    actor_id=actor_id,
                    actor_role="finance",
                    old_status=ClaimStatus.APPROVED,
                    new_status=ClaimStatus.PROCESSING,
                    comments=request.comments if request else None,
                ),
            )

            updated_claim = await self.claim_repo.find_by_claim_id(
                claim_id=claim_id,
                company_id=company_id,
            )

            return True, self._success(
                data={"claim": self._to_private_response(updated_claim)},
                message="Payment processing started successfully",
            )

        except Exception as exc:
            return False, self._error(
                "PAYMENT_PROCESSING_FAILED",
                f"Failed to start payment processing: {str(exc)}",
            )

    async def mark_claim_paid(
        self,
        claim_id: str,
        actor_id: str,
        request: MarkClaimPaidRequest,
        company_id: str = "default",
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Mark claim as paid.
        """
        try:
            company_id = self._normalize_company_id(company_id)

            claim, error = await self._get_claim_or_error(claim_id, company_id)
            if error:
                return False, error

            read_only_error = self._ensure_not_read_only(claim)
            if read_only_error:
                return False, read_only_error

            if claim.get("status") not in {
                ClaimStatus.APPROVED.value,
                ClaimStatus.PROCESSING.value,
            }:
                return False, self._error(
                    "CLAIM_NOT_PAYABLE",
                    "Only approved or processing claims can be marked paid",
                )

            approved_amount = claim.get("approved_amount") or claim.get("amount")

            if request.paid_amount > approved_amount:
                return False, self._error(
                    "INVALID_PAID_AMOUNT",
                    "Paid amount cannot exceed approved amount",
                )

            success = await self.claim_repo.mark_paid(
                claim_id=claim_id,
                company_id=company_id,
                payment_reference=request.payment_reference,
                payment_date=request.payment_date,
                paid_amount=request.paid_amount,
            )

            if not success:
                return False, self._error(
                    "PAYMENT_UPDATE_FAILED",
                    "Failed to mark claim as paid",
                )

            await self.claim_repo.add_action_history(
                claim_id=claim_id,
                company_id=company_id,
                action_event=self._build_action_event(
                    action=ClaimActionType.PAID,
                    actor_id=actor_id,
                    actor_role="finance",
                    old_status=ClaimStatus(claim["status"]),
                    new_status=ClaimStatus.PAID,
                    comments=request.comments,
                    amount=request.paid_amount,
                    extra_data={"payment_reference": request.payment_reference},
                ),
            )

            updated_claim = await self.claim_repo.find_by_claim_id(
                claim_id=claim_id,
                company_id=company_id,
            )

            return True, self._success(
                data={"claim": self._to_private_response(updated_claim)},
                message="Claim marked as paid successfully",
            )

        except Exception as exc:
            return False, self._error(
                "PAYMENT_UPDATE_FAILED",
                f"Failed to mark claim paid: {str(exc)}",
            )

    async def mark_payment_failed(
        self,
        claim_id: str,
        actor_id: str,
        request: MarkClaimPaymentFailedRequest,
        company_id: str = "default",
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Mark claim payment as failed.
        """
        try:
            company_id = self._normalize_company_id(company_id)

            claim, error = await self._get_claim_or_error(claim_id, company_id)
            if error:
                return False, error

            read_only_error = self._ensure_not_read_only(claim)
            if read_only_error:
                return False, read_only_error

            success = await self.claim_repo.mark_payment_failed(
                claim_id=claim_id,
                company_id=company_id,
                payment_failure_reason=request.payment_failure_reason,
            )

            if not success:
                return False, self._error(
                    "PAYMENT_FAILED_UPDATE_FAILED",
                    "Failed to update payment failure",
                )

            await self.claim_repo.add_action_history(
                claim_id=claim_id,
                company_id=company_id,
                action_event=self._build_action_event(
                    action=ClaimActionType.PAYMENT_FAILED,
                    actor_id=actor_id,
                    actor_role="finance",
                    old_status=ClaimStatus(claim["status"]),
                    new_status=ClaimStatus.FAILED,
                    comments=request.payment_failure_reason,
                ),
            )

            updated_claim = await self.claim_repo.find_by_claim_id(
                claim_id=claim_id,
                company_id=company_id,
            )

            return True, self._success(
                data={"claim": self._to_private_response(updated_claim)},
                message="Payment marked as failed",
            )

        except Exception as exc:
            return False, self._error(
                "PAYMENT_FAILED_UPDATE_FAILED",
                f"Failed to mark payment failed: {str(exc)}",
            )

    async def update_payment_status(
        self,
        claim_id: str,
        actor_id: str,
        request: UpdatePaymentStatusRequest,
        company_id: str = "default",
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Generic payment status update.

        Kept for compatibility. Prefer specific methods:
        - start_payment_processing
        - mark_claim_paid
        - mark_payment_failed
        """
        if request.payment_status == ClaimPaymentStatus.PROCESSING:
            return await self.start_payment_processing(
                claim_id=claim_id,
                actor_id=actor_id,
                request=StartClaimPaymentProcessingRequest(comments=request.comments),
                company_id=company_id,
            )

        if request.payment_status == ClaimPaymentStatus.PAID:
            return await self.mark_claim_paid(
                claim_id=claim_id,
                actor_id=actor_id,
                request=MarkClaimPaidRequest(
                    payment_reference=request.payment_reference,
                    payment_date=request.payment_date,
                    paid_amount=request.paid_amount,
                    comments=request.comments,
                ),
                company_id=company_id,
            )

        if request.payment_status == ClaimPaymentStatus.FAILED:
            return await self.mark_payment_failed(
                claim_id=claim_id,
                actor_id=actor_id,
                request=MarkClaimPaymentFailedRequest(
                    payment_failure_reason=request.payment_failure_reason,
                    comments=request.comments,
                ),
                company_id=company_id,
            )

        return False, self._error(
            "UNSUPPORTED_PAYMENT_STATUS",
            f"Unsupported payment status: {request.payment_status}",
        )

    # ---------------------------------------------------------------------
    # Validation / limit checks
    # ---------------------------------------------------------------------

    async def validate_claim(
        self,
        employee_id: str,
        request: ValidateClaimRequest,
        company_id: str = "default",
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Validate a claim before actual creation/submission.
        """
        try:
            company_id = self._normalize_company_id(company_id)

            claim_type, claim_type_error = await self._get_claim_type_or_error(
                request.claim_type_id
            )
            if claim_type_error:
                return False, claim_type_error

            company_policy = await self._get_company_claim_policy(company_id)

            policy_snapshot = self._build_policy_snapshot(
                claim_type=claim_type,
                company_policy=company_policy,
                currency=request.currency,
            )

            errors: List[str] = []
            warnings: List[str] = []

            duplicate = await self.claim_repo.find_recent_similar_claim(
                employee_id=employee_id,
                claim_type_id=request.claim_type_id,
                amount=request.amount,
                expense_date=request.expense_date,
                company_id=company_id,
                within_hours=48,
            )

            duplicate_check = {
                "has_duplicate": duplicate is not None,
                "duplicate_claim_id": duplicate.get("claim_id") if duplicate else None,
            }

            if duplicate:
                warnings.append(
                    f"Similar claim already exists: {duplicate.get('claim_id')}"
                )

            limit_check = await self._check_claim_limit(
                employee_id=employee_id,
                claim_type=claim_type,
                policy_snapshot=policy_snapshot,
                amount=request.amount,
                company_id=company_id,
            )

            if not limit_check.get("can_claim", False):
                errors.append(limit_check.get("message", "Claim limit exceeded"))

            bill_error = self._check_bill_requirement(
                amount=request.amount,
                attachments_count=request.attachment_count,
                policy_snapshot=policy_snapshot,
            )

            bill_requirement = {
                "requires_bill": bill_error is not None,
                "attachment_count": request.attachment_count,
            }

            if bill_error:
                errors.append(bill_error["message"])

            approval_steps = self._build_approval_steps(
                amount=request.amount,
                employee_snapshot={},
                policy_snapshot=policy_snapshot,
            )

            response = ClaimValidationResponse(
                is_valid=len(errors) == 0,
                errors=errors,
                warnings=warnings,
                limit_check=limit_check,
                duplicate_check=duplicate_check,
                bill_requirement=bill_requirement,
                policy_check=policy_snapshot.model_dump(),
                approval_preview={
                    "requires_approval": True,
                    "auto_approval_disabled": True,
                    "approval_steps": [
                        step.model_dump() for step in approval_steps
                    ],
                },
            )

            return True, self._success(
                data=response.model_dump(),
                message="Claim validation completed",
            )

        except Exception as exc:
            return False, self._error(
                "CLAIM_VALIDATION_FAILED",
                f"Failed to validate claim: {str(exc)}",
            )

    async def check_claim_limit(
        self,
        employee_id: str,
        claim_type_id: str,
        amount: float,
        company_id: str = "default",
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Check claim limits for a claim type.
        """
        try:
            company_id = self._normalize_company_id(company_id)

            claim_type, claim_type_error = await self._get_claim_type_or_error(
                claim_type_id
            )
            if claim_type_error:
                return False, claim_type_error

            company_policy = await self._get_company_claim_policy(company_id)

            policy_snapshot = self._build_policy_snapshot(
                claim_type=claim_type,
                company_policy=company_policy,
                currency=claim_type.get("currency", "INR"),
            )

            result = await self._check_claim_limit(
                employee_id=employee_id,
                claim_type=claim_type,
                policy_snapshot=policy_snapshot,
                amount=amount,
                company_id=company_id,
            )

            return True, self._success(
                data=result,
                message="Claim limit check completed",
            )

        except Exception as exc:
            return False, self._error(
                "LIMIT_CHECK_FAILED",
                f"Failed to check claim limit: {str(exc)}",
            )

    # ---------------------------------------------------------------------
    # Statistics / dashboard
    # ---------------------------------------------------------------------

    async def get_my_statistics(
        self,
        employee_id: str,
        company_id: str = "default",
        year: Optional[int] = None,
        month: Optional[int] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Get claim statistics for employee.
        """
        try:
            company_id = self._normalize_company_id(company_id)

            stats = await self.claim_repo.get_employee_statistics(
                employee_id=employee_id,
                company_id=company_id,
                year=year,
                month=month,
            )

            current_year = Date.today().year
            current_month = Date.today().month

            monthly_stats = await self.claim_repo.get_employee_statistics(
                employee_id=employee_id,
                company_id=company_id,
                year=current_year,
                month=current_month,
            )

            yearly_stats = await self.claim_repo.get_employee_statistics(
                employee_id=employee_id,
                company_id=company_id,
                year=current_year,
            )

            stats["monthly_total"] = monthly_stats.get("total_amount_claimed", 0.0)
            stats["yearly_total"] = yearly_stats.get("total_amount_claimed", 0.0)
            stats.setdefault("currency", "INR")

            response = ClaimStatistics(**stats)

            return True, self._success(
                data=response.model_dump(),
                message="Claim statistics retrieved successfully",
            )

        except Exception as exc:
            return False, self._error(
                "STATISTICS_FAILED",
                f"Failed to retrieve statistics: {str(exc)}",
            )

    async def get_dashboard(
        self,
        filters: ClaimDashboardFilters,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Get HR/Admin/Finance claim dashboard.
        """
        try:
            company_id = self._normalize_company_id(filters.company_id)

            stats = await self.claim_repo.get_dashboard_statistics(
                company_id=company_id,
                from_date=filters.from_date,
                to_date=filters.to_date,
                department_id=filters.department_id,
                manager_id=filters.manager_id,
                claim_type_id=filters.claim_type_id,
            )

            stats["currency"] = filters.currency
            dashboard_stats = ClaimDashboardStatistics(**stats)

            recent_claims = await self.claim_repo.list_claims(
                company_id=company_id,
                department_id=filters.department_id,
                manager_id=filters.manager_id,
                claim_type_id=filters.claim_type_id,
                from_date=filters.from_date,
                to_date=filters.to_date,
                skip=0,
                limit=10,
                sort_by="created_at",
                sort_order="desc",
            )

            pending_claims = await self.claim_repo.find_pending_approvals(
                company_id=company_id,
                department_id=filters.department_id,
                claim_type_id=filters.claim_type_id,
                skip=0,
                limit=10,
            )

            pending_count = await self.claim_repo.count_pending_approvals(
                company_id=company_id,
                department_id=filters.department_id,
                claim_type_id=filters.claim_type_id,
            )

            return True, self._success(
                data={
                    "statistics": dashboard_stats.model_dump(),
                    "recent_claims": [
                        self._to_summary(claim) for claim in recent_claims
                    ],
                    "pending_approvals": [
                        self._to_summary(claim) for claim in pending_claims
                    ],
                    "pending_approvals_count": pending_count,
                },
                message="Claim dashboard retrieved successfully",
            )

        except Exception as exc:
            return False, self._error(
                "DASHBOARD_FAILED",
                f"Failed to retrieve claim dashboard: {str(exc)}",
            )