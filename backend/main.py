from fastapi import FastAPI
from app.db.database import db
from app.routes.auth_routes import router as auth_router
from app.routes.super_admin_routes import router as super_admin_router
from app.routes.admin_routes import router as admin_router
from app.routes.hr_routes import router as hr_router

app=FastAPI()

app.include_router(auth_router)

@app.get("/")
def home():
    return {"message": "HR AI A gent backend running successfully!"}







app.include_router(super_admin_router)
app.include_router(admin_router)
app.include_router(hr_router)