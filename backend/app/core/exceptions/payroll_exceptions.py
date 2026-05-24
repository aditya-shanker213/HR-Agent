from typing import Any

from .base import BaseAppException


class PayrollException(BaseAppException):
    def __init__(
        self,
        message: str,
        error_code: str = "PAY_BASE",
        status_code: int = 422,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=status_code,
            details=details,
        )


class PayslipNotFoundException(PayrollException):
    def __init__(
        self,
        message: str = "No payroll record found for the requested period.",
        requested_month: int | None = None,
        requested_year: int | None = None,
        processing_date: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if requested_month is not None:
            merged_details["requested_month"] = requested_month
        if requested_year is not None:
            merged_details["requested_year"] = requested_year
        if processing_date:
            merged_details["processing_date"] = processing_date
        super().__init__(
            message=message,
            error_code="PAY_001",
            status_code=404,
            details=merged_details,
        )


class UnauthorizedPayrollAccessException(PayrollException):
    def __init__(
        self,
        message: str = "Access to the requested payroll data is not authorized.",
        target_employee_id: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if target_employee_id:
            merged_details["target_employee_id"] = target_employee_id
        super().__init__(
            message=message,
            error_code="PAY_002",
            status_code=403,
            details=merged_details,
        )


class SalaryMismatchException(PayrollException):
    def __init__(
        self,
        message: str = "Computed salary does not match the stored payroll record.",
        stored_net_salary: float | None = None,
        computed_net_salary: float | None = None,
        tolerance: float | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if stored_net_salary is not None:
            merged_details["stored_net_salary"] = stored_net_salary
        if computed_net_salary is not None:
            merged_details["computed_net_salary"] = computed_net_salary
        if tolerance is not None:
            merged_details["tolerance"] = tolerance
        super().__init__(
            message=message,
            error_code="PAY_003",
            status_code=422,
            details=merged_details,
        )