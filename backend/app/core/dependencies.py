"""
FastAPI dependencies for authentication and role-based access control.

`get_current_user` decodes the bearer token and loads the corresponding
User from the database on every protected request. `require_roles(...)`
builds a dependency that additionally checks the user's role against an
allow-list, for endpoints restricted to specific roles (e.g. only ADMIN
can change another user's role).
"""
from typing import Callable

from fastapi import Depends, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.exceptions import AuthenticationException, AuthorizationException
from app.core.security import JWTError, decode_access_token
from app.database.session import get_db
from app.models.roles import UserRole
from app.models.user import User
from app.repositories.user_repository import UserRepository

# tokenUrl points at the login endpoint so interactive API docs
# (/api/docs) can authenticate via the "Authorize" button.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Resolve the currently authenticated user from the bearer token.

    Re-fetches the user from the database on every request (rather than
    trusting the JWT payload alone) so that role changes or account
    deactivation take effect immediately, without waiting for the token
    to expire.
    """
    if not token:
        raise AuthenticationException("Not authenticated")

    try:
        payload = decode_access_token(token)
    except JWTError:
        raise AuthenticationException("Invalid or expired token")

    username = payload.get("sub")
    if not username:
        raise AuthenticationException("Invalid token payload")

    user = UserRepository(db).get_by_username(username)
    if not user:
        raise AuthenticationException("User no longer exists")
    if not user.is_active:
        raise AuthenticationException("This account has been deactivated")

    return user


def require_roles(*allowed_roles: UserRole) -> Callable[..., User]:
    """
    Build a dependency that restricts an endpoint to specific roles.

    Usage:
        @router.delete(..., dependencies=[Depends(require_roles(UserRole.ADMIN))])
        or
        def endpoint(user: User = Depends(require_roles(UserRole.ADMIN))):
    """
    allowed_values = {role.value for role in allowed_roles}

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_values:
            raise AuthorizationException(
                f"This action requires one of the following roles: {sorted(allowed_values)}"
            )
        return current_user

    return dependency


# Convenience pre-built dependencies for common role combinations used
# across multiple routers in later phases.
require_admin = require_roles(UserRole.ADMIN)
require_manager_or_admin = require_roles(UserRole.ADMIN, UserRole.FINANCE_MANAGER)
require_any_finance_role = require_roles(
    UserRole.ADMIN, UserRole.FINANCE_MANAGER, UserRole.FINANCE_ANALYST
)
# Audit logs are oversight data: only AUDITOR (their core function) and
# ADMIN (full platform access) may view the system-wide log. Notably
# excludes FINANCE_MANAGER -- managers approve/reject documents but
# don't get a cross-cutting view of every user's activity.
require_auditor_or_admin = require_roles(UserRole.AUDITOR, UserRole.ADMIN)
