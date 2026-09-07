"""
WorkflowHistory repository: data-access layer.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workflow_history import WorkflowHistory


class WorkflowHistoryRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_for_document(self, document_id: int) -> list[WorkflowHistory]:
        """Oldest first -- workflow history reads naturally as a timeline."""
        stmt = (
            select(WorkflowHistory)
            .where(WorkflowHistory.document_id == document_id)
            .order_by(WorkflowHistory.created_at.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def create(
        self,
        *,
        document_id: int,
        action: str,
        from_status: str,
        to_status: str,
        performed_by: int,
        comment: str | None = None,
    ) -> WorkflowHistory:
        entry = WorkflowHistory(
            document_id=document_id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            performed_by=performed_by,
            comment=comment,
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry
