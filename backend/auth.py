from datetime import datetime, timedelta
from jose import jwt, JWTError
import hashlib
import hmac
import os
import base64
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from backend.config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRY_HOURS

security = HTTPBearer(auto_error=False)


def hash_pin(pin: str) -> str:
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac('sha256', pin.encode(), salt, 100000)
    return base64.b64encode(salt + key).decode()


def verify_pin(plain: str, hashed: str) -> bool:
    try:
        decoded = base64.b64decode(hashed.encode())
        salt = decoded[:16]
        stored_key = decoded[16:]
        key = hashlib.pbkdf2_hmac('sha256', plain.encode(), salt, 100000)
        return hmac.compare_digest(key, stored_key)
    except Exception:
        return False


def create_token(data: dict) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return decode_token(credentials.credentials)


async def get_optional_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        return None
    try:
        return decode_token(credentials.credentials)
    except Exception:
        return None
