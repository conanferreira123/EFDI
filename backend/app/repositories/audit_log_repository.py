"""
AuditLog repository: data-access layer.
"""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


class AuditLogRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        action: str,
        user_id: int | None,
        document_id: int | None = None,
        details: dict | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            action=action,
            user_id=user_id,
            document_id=document_id,
            details=details,
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def search(
        self,
        *,
        action: str | None = None,
        user_id: int | None = None,
        document_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[AuditLog], int]:
        """
        Returns (page_of_results, total_matching_count), newest first.
        Mirrors DocumentRepository.search's pagination shape so list
        endpoints across the app behave consistently.
        """
        conditions = []

        if action is not None:
            conditions.append(AuditLog.action == action)
        if user_id is not None:
            conditions.append(AuditLog.user_id == user_id)
        if document_id is not None:
            conditions.append(AuditLog.document_id == document_id)
        if date_from is not None:
            conditions.append(AuditLog.created_at >= date_from)
        if date_to is not None:
            conditions.append(AuditLog.created_at <= date_to)

        count_stmt = select(func.count()).select_from(AuditLog).where(*conditions)
        total = self.db.execute(count_stmt).scalar_one()

        stmt = (
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        results = list(self.db.execute(stmt).scalars().all())

        return results, total

    def list_for_document(self, document_id: int) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.document_id == document_id)
            .order_by(AuditLog.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

