from pydantic import BaseModel, EmailStr


class CreateAdminSchema(BaseModel):

    name: str
    email: EmailStr
    password: str
    
class LoginSchema(BaseModel):

    email: EmailStr
    password: str

class CreateHRSchema(BaseModel):

    name: str
    email: EmailStr
    password: str
    
# CREATE EMPLOYEE


class CreateEmployeeSchema(BaseModel):

    name: str
    email: EmailStr
    password: str

    department: str

    designation: str