from app.db.database import db


# =========================
# GET SAFE EMPLOYEE CONTEXT
# =========================

def get_employee_context(email: str):

    users_collection = db["users"]

    employee = users_collection.find_one({

        "email": email
    })

    if not employee:

        return None

    # Return ONLY safe fields
    return {

        "employee_id": employee.get("employee_id"),

        "name": employee.get("name"),

        "department": employee.get("department"),

        "designation": employee.get("designation"),

        "role": employee.get("role")
    }


# =========================
# BUILD AI CONTEXT
# =========================

def build_ai_context(

    user_query: str,

    employee_context: dict
):

    return {

        "user_query": user_query,

        "employee_context": employee_context
    }