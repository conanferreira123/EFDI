"""
Authentication routes: register, login, and current-user lookup.
"""
import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.core.exceptions import AuthenticationException
from app.database.session import get_db
from app.models.document_enums import AuditAction
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserLogin, UserResponse
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> UserResponse:
    """
    Register a new user.

    NOTE: in a hardened production deployment, self-service registration
    with an arbitrary role would typically be restricted (e.g. new
    registrations default to FINANCE_ANALYST, and only an ADMIN can
    promote someone via PATCH /users/{id}/role). This phase exposes role
    selection at registration to make the four target roles easy to
    create and test; the admin-promotion endpoint is added alongside it
    for completeness.
    """
    service = AuthService(db)
    user = service.register(payload)

    AuditService(db).log(
        AuditAction.USER_REGISTERED,
        user_id=user.id,
        details={"username": user.username, "role": user.role},
    )

    return UserResponse.model_validate(user)


@router.post("/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)) -> Token:
    """Authenticate with username/password and receive a JWT access token."""
    service = AuthService(db)
    audit_service = AuditService(db)

    try:
        token = service.login(payload.username, payload.password)
    except AuthenticationException:
        # user_id is intentionally None here: at this point we haven't
        # established who, if anyone, this username actually belongs
        # to -- AuthService deliberately gives the same error for "no
        # such user" and "wrong password" to prevent username
        # enumeration, and the audit log must not undo that by
        # resolving the username to a real user_id on failure. The
        # attempted username is still recorded in `details` since
        # that's valuable for spotting brute-force patterns.
        audit_service.log(
            AuditAction.LOGIN_FAILED,
            user_id=None,
            details={"attempted_username": payload.username},
        )
        raise

    audit_service.log(
        AuditAction.LOGIN_SUCCESS,
        user_id=token.user.id,
        details={"username": token.user.username},
    )
    return token


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Return the profile of the currently authenticated user."""
    return UserResponse.model_validate(current_user)
