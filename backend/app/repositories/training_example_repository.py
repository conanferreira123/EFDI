"""
TrainingExample repository: data-access layer.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.training_example import TrainingExample


class TrainingExampleRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_by_task_type(self, task_type: str) -> list[TrainingExample]:
        stmt = (
            select(TrainingExample)
            .where(TrainingExample.task_type == task_type)
            .order_by(TrainingExample.created_at.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def count_by_task_and_type(self, task_type: str) -> dict[str, int]:
        """
        Returns {document_type: count} for a given task -- used by the
        training script to decide whether there's enough data per
        class to bother training, before it ever touches sklearn.
        """
        stmt = (
            select(TrainingExample.document_type, func.count())
            .where(TrainingExample.task_type == task_type)
            .group_by(TrainingExample.document_type)
        )
        return {doc_type: count for doc_type, count in self.db.execute(stmt).all()}
