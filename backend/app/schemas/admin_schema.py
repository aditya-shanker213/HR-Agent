# backend/app/schemas/admin_schema.py
from pydantic import BaseModel, EmailStr
from typing import Optional


class CreateAdminSchema(BaseModel):
    name:     str
    email:    EmailStr
    password: str


class LoginSchema(BaseModel):
    email:    EmailStr
    password: str


class CreateHRSchema(BaseModel):
    name:     str
    email:    EmailStr
    password: str


class CreateEmployeeSchema(BaseModel):
    name:        str
    email:       EmailStr
    password:    str
    department:  str
    designation: str