"""
Pydantic schemas for users and authentication.
"""
import re

from pydantic import EmailStr, Field, field_validator

from app.models.roles import UserRole
from app.schemas.base import BaseSchema, TimestampSchema

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")


class UserCreate(BaseSchema):
    """Payload for registering a new user."""

    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = UserRole.FINANCE_ANALYST

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not USERNAME_PATTERN.match(v):
            raise ValueError(
                "Username may only contain letters, numbers, dots, underscores, and hyphens"
            )
        return v

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
            raise ValueError("Password must contain at least one letter and one digit")
        return v


class UserLogin(BaseSchema):
    """Payload for logging in."""

    username: str
    password: str


class UserResponse(TimestampSchema):
    """Public-facing user representation. Never includes password_hash."""

    id: int
    username: str
    email: str
    full_name: str
    role: UserRole
    is_active: bool


class UserUpdateRole(BaseSchema):
    """Admin-only payload for changing a user's role."""

    role: UserRole


class UserUpdateStatus(BaseSchema):
    """Admin-only payload for activating/deactivating a user."""

    is_active: bool


class Token(BaseSchema):
    """Response returned on successful login."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class TokenPayload(BaseSchema):
    """Decoded JWT payload shape, used internally."""

    sub: str  # username
    user_id: int
    role: str
    exp: int
