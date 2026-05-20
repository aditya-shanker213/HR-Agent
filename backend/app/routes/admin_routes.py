from fastapi import APIRouter, Depends

from app.schemas.admin_schema import CreateHRSchema

from app.services.auth_service import hash_password

from app.utils.auth_dependencies import require_roles

from app.db.database import db

router = APIRouter()


# =========================
# ADMIN CREATE HR
# =========================

@router.post("/admin/create-hr")
def create_hr(

    hr: CreateHRSchema,

    current_user: dict = Depends(
        require_roles([
            "admin",
            "super_admin"
        ])
    )
):

    users_collection = db["users"]

    existing_hr = users_collection.find_one({
        "email": hr.email
    })

    if existing_hr:

        return {
            "message": "HR already exists"
        }

    hashed_password = hash_password(
        hr.password
    )

    hr_data = {

        "name": hr.name,

        "email": hr.email,

        "password": hashed_password,

        "role": "hr",

        "created_by": current_user["email"]
    }

    users_collection.insert_one(hr_data)

    return {
        "message": "HR created successfully"
    }