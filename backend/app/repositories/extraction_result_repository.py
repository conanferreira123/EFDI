"""
ExtractionResult repository: data-access layer.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.extraction_result import ExtractionResult


class ExtractionResultRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, extraction_result_id: int) -> ExtractionResult | None:
        return self.db.get(ExtractionResult, extraction_result_id)

    def get_latest_for_document(self, document_id: int) -> ExtractionResult | None:
        stmt = (
            select(ExtractionResult)
            .where(ExtractionResult.document_id == document_id)
            .order_by(ExtractionResult.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_document(self, document_id: int) -> list[ExtractionResult]:
        stmt = (
            select(ExtractionResult)
            .where(ExtractionResult.document_id == document_id)
            .order_by(ExtractionResult.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def create(
        self,
        *,
        document_id: int,
        document_type: str,
        engine_name: str,
        fields: dict,
        overall_confidence: float,
        fields_found_count: int,
        fields_total_count: int,
    ) -> ExtractionResult:
        result = ExtractionResult(
            document_id=document_id,
            document_type=document_type,
            engine_name=engine_name,
            fields=fields,
            overall_confidence=overall_confidence,
            fields_found_count=fields_found_count,
            fields_total_count=fields_total_count,
        )
        self.db.add(result)
        self.db.commit()
        self.db.refresh(result)
        return result

    def update_field(self, extraction_result: ExtractionResult, field_key: str, value: str) -> ExtractionResult:
        """
        Manually correct/fill a single field, marking it as
        human-entered (confidence 1.0, no matched_text since it wasn't
        OCR-matched). Mutates the JSONB fields dict in place.
        """
        fields = dict(extraction_result.fields)
        fields[field_key] = {
            "value": value,
            "confidence": 1.0,
            "matched_text": None,
            "is_found": True,
            "manually_entered": True,
        }
        extraction_result.fields = fields

        found_count = sum(1 for f in fields.values() if f.get("is_found"))
        extraction_result.fields_found_count = found_count

        self.db.commit()
        self.db.refresh(extraction_result)
        return extraction_result
