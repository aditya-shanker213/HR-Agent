# backend/app/routes/admin_routes.py
from fastapi import APIRouter, Depends
from app.schemas.admin_schema import CreateHRSchema, CreateEmployeeSchema
from app.services.auth_service import hash_password
from app.utils.auth_dependencies import require_roles
from app.db.database import db
import uuid

router = APIRouter(tags=["admin"])


@router.post("/admin/create-hr")
def create_hr(
    hr: CreateHRSchema,
    current_user: dict = Depends(require_roles(["admin", "super_admin"]))
):
    users_collection = db["users"]
    if users_collection.find_one({"email": hr.email}):
        return {"message": "HR already exists"}

    users_collection.insert_one({
        "name":       hr.name,
        "email":      hr.email,
        "password":   hash_password(hr.password),
        "role":       "hr",
        "created_by": current_user["email"],
    })
    return {"message": "HR created successfully"}


@router.post("/admin/create-employee")
def create_employee(
    emp: CreateEmployeeSchema,
    current_user: dict = Depends(require_roles(["admin", "super_admin", "hr"]))
):
    users_collection = db["users"]
    if users_collection.find_one({"email": emp.email}):
        return {"message": "Employee already exists"}

    # Generate emp_id — used as user_id in leave/payroll/claims
    emp_id = f"emp_{uuid.uuid4().hex[:6]}"

    users_collection.insert_one({
        "name":        emp.name,
        "email":       emp.email,
        "password":    hash_password(emp.password),
        "role":        "employee",
        "emp_id":      emp_id,
        "department":  emp.department,
        "designation": emp.designation,
        "created_by":  current_user["email"],
        # Leave balance seeded on creation
        "leave_balance": {
            "casual":    12,
            "sick":      12,
            "earned":    15,
            "emergency": 3,
        },
    })
    return {"message": "Employee created successfully", "emp_id": emp_id}