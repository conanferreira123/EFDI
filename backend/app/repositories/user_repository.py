"""
User repository: data-access layer for the User model.

Services call into this layer rather than issuing raw queries directly,
so the data-access pattern stays consistent as more entities (Document,
AuditLog, etc.) are added in later phases.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_all(self, *, skip: int = 0, limit: int = 100) -> list[User]:
        stmt = select(User).order_by(User.id).offset(skip).limit(limit)
        return list(self.db.execute(stmt).scalars().all())

    def create(self, *, username: str, email: str, full_name: str, password_hash: str, role: str) -> User:
        user = User(
            username=username,
            email=email,
            full_name=full_name,
            password_hash=password_hash,
            role=role,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_role(self, user: User, role: str) -> User:
        user.role = role
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_status(self, user: User, is_active: bool) -> User:
        user.is_active = is_active
        self.db.commit()
        self.db.refresh(user)
        return user
