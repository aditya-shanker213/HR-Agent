# backend/app/routes/auth_routes.py
from fastapi import APIRouter, Depends
from app.schemas.admin_schema import LoginSchema
from app.services.auth_service import verify_password
from app.utils.jwt_handler import create_access_token
from app.utils.auth_dependencies import get_current_user
from app.db.database import db

router = APIRouter(tags=["auth"])


@router.post("/login")
def login(user: LoginSchema):
    users_collection = db["users"]
    existing_user    = users_collection.find_one({"email": user.email})

    if not existing_user:
        return {"message": "Invalid email or password"}

    if not verify_password(user.password, existing_user["password"]):
        return {"message": "Invalid email or password"}

    token_data = {
        "user_id": str(existing_user["_id"]),
        "email":   existing_user["email"],
        "role":    existing_user["role"],
        "name":    existing_user.get("name", ""),
    }
    if existing_user.get("emp_id"):
        token_data["emp_id"] = existing_user["emp_id"]

    # Add emp_id if employee — used by voice.py to fetch MongoDB data
    if existing_user.get("emp_id"):
        token_data["emp_id"] = existing_user["emp_id"]

    access_token = create_access_token(token_data)
    return {"access_token": access_token, "role": existing_user["role"]}


@router.get("/me")
def get_me(current_user: dict = Depends(get_current_user)):
    return {"current_user": current_user}