# backend/app/routes/super_admin_routes.py
from fastapi import APIRouter, Depends
from app.schemas.admin_schema import CreateAdminSchema
from app.services.auth_service import hash_password
from app.utils.auth_dependencies import require_roles
from app.db.database import db

router = APIRouter(tags=["super_admin"])


@router.post("/super-admin/create-admin")
def create_admin(
    admin: CreateAdminSchema,
    current_user: dict = Depends(require_roles(["super_admin"]))
):
    users_collection = db["users"]
    if users_collection.find_one({"email": admin.email}):
        return {"message": "Admin already exists"}

    users_collection.insert_one({
        "name":       admin.name,
        "email":      admin.email,
        "password":   hash_password(admin.password),
        "role":       "admin",
        "created_by": current_user["email"],
    })
    return {"message": "Admin created successfully"}