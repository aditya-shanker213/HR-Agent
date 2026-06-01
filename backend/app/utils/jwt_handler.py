# backend/app/utils/jwt_handler.py
from jose import jwt
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

load_dotenv()

JWT_SECRET    = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")


def create_access_token(data: dict):
    token_data  = data.copy()
    expire_time = datetime.utcnow() + timedelta(hours=2)
    token_data.update({"exp": expire_time})
    return jwt.encode(token_data, JWT_SECRET, algorithm=JWT_ALGORITHM)