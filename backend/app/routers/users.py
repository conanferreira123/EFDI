"""
User management routes.

These endpoints exist specifically to exercise and demonstrate
role-based access control: only ADMIN can list all users, change a
user's role, or activate/deactivate an account. Any authenticated user
can view their own profile via GET /auth/me (see app/routers/auth.py).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import require_admin
from app.core.exceptions import NotFoundException
from app.database.session import get_db
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserResponse, UserUpdateRole, UserUpdateStatus

router = APIRouter(prefix="/users", tags=["User Management"])


@router.get("", response_model=list[UserResponse], dependencies=[Depends(require_admin)])
def list_users(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)) -> list[UserResponse]:
    """List all users. ADMIN only."""
    users = UserRepository(db).list_all(skip=skip, limit=limit)
    return [UserResponse.model_validate(u) for u in users]


@router.get("/{user_id}", response_model=UserResponse, dependencies=[Depends(require_admin)])
def get_user(user_id: int, db: Session = Depends(get_db)) -> UserResponse:
    """Fetch a single user by id. ADMIN only."""
    user = UserRepository(db).get_by_id(user_id)
    if not user:
        raise NotFoundException("User", user_id)
    return UserResponse.model_validate(user)


@router.patch("/{user_id}/role", response_model=UserResponse, dependencies=[Depends(require_admin)])
def update_user_role(user_id: int, payload: UserUpdateRole, db: Session = Depends(get_db)) -> UserResponse:
    """Change a user's role. ADMIN only."""
    repo = UserRepository(db)
    user = repo.get_by_id(user_id)
    if not user:
        raise NotFoundException("User", user_id)
    updated = repo.update_role(user, payload.role.value)
    return UserResponse.model_validate(updated)


@router.patch("/{user_id}/status", response_model=UserResponse, dependencies=[Depends(require_admin)])
def update_user_status(user_id: int, payload: UserUpdateStatus, db: Session = Depends(get_db)) -> UserResponse:
    """Activate or deactivate a user account. ADMIN only."""
    repo = UserRepository(db)
    user = repo.get_by_id(user_id)
    if not user:
        raise NotFoundException("User", user_id)
    updated = repo.update_status(user, payload.is_active)
    return UserResponse.model_validate(updated)
