"""
ValidationResult repository: data-access layer.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.validation_result import ValidationResult


class ValidationResultRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_latest_for_document(self, document_id: int) -> ValidationResult | None:
        stmt = (
            select(ValidationResult)
            .where(ValidationResult.document_id == document_id)
            .order_by(ValidationResult.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_document(self, document_id: int) -> list[ValidationResult]:
        stmt = (
            select(ValidationResult)
            .where(ValidationResult.document_id == document_id)
            .order_by(ValidationResult.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def create(
        self,
        *,
        document_id: int,
        document_type: str,
        engine_name: str,
        is_valid: bool,
        error_count: int,
        warning_count: int,
        issues: list,
    ) -> ValidationResult:
        result = ValidationResult(
            document_id=document_id,
            document_type=document_type,
            engine_name=engine_name,
            is_valid=is_valid,
            error_count=error_count,
            warning_count=warning_count,
            issues=issues,
        )
        self.db.add(result)
        self.db.commit()
        self.db.refresh(result)
        return result
