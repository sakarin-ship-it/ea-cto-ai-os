"""JWT authentication + 4-role authorisation for EA-DIS API.

Roles: ADMIN > REVIEWER > OPERATOR > VIEWER
Secrets from environment variables only (never hardcoded).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from ea_dis.constants import Role

_JWT_SECRET = os.environ.get("EA_DIS_JWT_SECRET", "change-me-in-production")
_JWT_ALGORITHM = "HS256"
_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("EA_DIS_TOKEN_EXPIRE_MINUTES", "60"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()

# Role hierarchy: higher index = more privilege
_ROLE_RANK: dict[Role, int] = {
    Role.VIEWER: 0,
    Role.OPERATOR: 1,
    Role.REVIEWER: 2,
    Role.ADMIN: 3,
}


class TokenPayload(BaseModel):
    sub: str
    role: Role
    exp: int


def create_access_token(subject: str, role: Role) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "role": role.value, "exp": int(expire.timestamp())}
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def verify_token(token: str) -> TokenPayload:
    try:
        data = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        return TokenPayload(sub=data["sub"], role=Role(data["role"]), exp=data["exp"])
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> TokenPayload:
    return verify_token(credentials.credentials)


def require_role(minimum: Role):
    """Dependency factory: raises 403 if user role is below minimum."""
    def _check(user: Annotated[TokenPayload, Depends(get_current_user)]) -> TokenPayload:
        if _ROLE_RANK[user.role] < _ROLE_RANK[minimum]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role {minimum.value} or higher required",
            )
        return user
    return _check


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)
