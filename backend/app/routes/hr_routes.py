from fastapi import APIRouter, Depends

from app.schemas.admin_schema import CreateEmployeeSchema

from app.services.auth_service import hash_password

from app.utils.auth_dependencies import require_roles

from app.db.database import db

router = APIRouter()


# =========================
# CREATE EMPLOYEE
# =========================

@router.post("/hr/create-employee")
def create_employee(

    employee: CreateEmployeeSchema,

    current_user: dict = Depends(

        require_roles([
            "hr",
            "admin",
            "super_admin"
        ])
    )
):

    users_collection = db["users"]

    existing_employee = users_collection.find_one({

        "email": employee.email
    })

    if existing_employee:

        return {
            "message": "Employee already exists"
        }

    employee_count = users_collection.count_documents({

        "role": "employee"
    })

    employee_id = f"EMP{employee_count + 1:03}"

    hashed_password = hash_password(
        employee.password
    )

    employee_data = {

        "employee_id": employee_id,

        "name": employee.name,

        "email": employee.email,

        "password": hashed_password,

        "department": employee.department,

        "designation": employee.designation,

        "role": "employee",

        "created_by": current_user["email"]
    }

    users_collection.insert_one(employee_data)

    return {

        "message": "Employee created successfully",

        "employee_id": employee_id
    }