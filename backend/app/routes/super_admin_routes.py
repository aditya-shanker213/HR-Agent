from fastapi import APIRouter, Depends

from app.schemas.admin_schema import CreateAdminSchema

from app.services.auth_service import hash_password

from app.utils.auth_dependencies import require_roles

from app.db.database import db

router = APIRouter()


# =========================
# SUPER ADMIN CREATE ADMIN
# =========================

@router.post("/super-admin/create-admin")
def create_admin(

    admin: CreateAdminSchema,

    current_user: dict = Depends(
        require_roles(["super_admin"])
    )
):

    users_collection = db["users"]

    existing_admin = users_collection.find_one({
        "email": admin.email
    })

    if existing_admin:

        return {
            "message": "Admin already exists"
        }

    hashed_password = hash_password(
        admin.password
    )

    admin_data = {

        "name": admin.name,

        "email": admin.email,

        "password": hashed_password,

        "role": "admin",

        "created_by": current_user["email"]
    }

    users_collection.insert_one(admin_data)

    return {
        "message": "Admin created successfully"
    }