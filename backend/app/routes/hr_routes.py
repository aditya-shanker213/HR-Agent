# backend/app/routes/hr_routes.py
from fastapi import APIRouter, Depends
from app.utils.auth_dependencies import require_roles

router = APIRouter(tags=["hr"])


@router.get("/hr/dashboard")
def hr_dashboard(
    current_user: dict = Depends(require_roles(["hr", "admin", "super_admin"]))
):
    return {"message": f"Welcome HR, {current_user.get('name', '')}"}