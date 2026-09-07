"""
Authentication service: business logic for registration and login.

Routers should call into this service rather than touching the
repository or security primitives directly, keeping HTTP concerns
(status codes, request parsing) fully separate from business rules
(uniqueness checks, credential verification).
"""
import logging

from sqlalchemy.orm import Session

from app.core.exceptions import AlreadyExistsException, AuthenticationException
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import Token, UserCreate, UserResponse

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = UserRepository(db)

    def register(self, payload: UserCreate) -> User:
        if self.repo.get_by_username(payload.username):
            raise AlreadyExistsException("User", "username", payload.username)
        if self.repo.get_by_email(payload.email):
            raise AlreadyExistsException("User", "email", payload.email)

        password_hash = hash_password(payload.password)
        user = self.repo.create(
            username=payload.username,
            email=payload.email,
            full_name=payload.full_name,
            password_hash=password_hash,
            role=payload.role.value,
        )
        logger.info("New user registered: username=%s role=%s", user.username, user.role)
        return user

    def authenticate(self, username: str, password: str) -> User:
        """
        Verify credentials and return the User if valid.

        Deliberately raises the same generic error for "user not found"
        and "wrong password" so the API never reveals which part of the
        credential pair was incorrect (standard practice to prevent
        username enumeration). Supports lookup by either username or email,
        trimming whitespace.
        """
        identifier = (username or "").strip()
        user = self.repo.get_by_username(identifier) or self.repo.get_by_email(identifier)
        if not user or not verify_password(password, user.password_hash):
            raise AuthenticationException("Incorrect username or password")
        if not user.is_active:
            raise AuthenticationException("This account has been deactivated")
        return user

    def login(self, username: str, password: str) -> Token:
        user = self.authenticate(username, password)
        token, expires_in = create_access_token(
            username=user.username, user_id=user.id, role=user.role
        )
        logger.info("User logged in: username=%s", user.username)
        return Token(
            access_token=token,
            expires_in=expires_in,
            user=UserResponse.model_validate(user),
        )
