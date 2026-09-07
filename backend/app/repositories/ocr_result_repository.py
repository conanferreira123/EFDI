"""
OCRResult repository: data-access layer for persisted OCR output.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ocr_result import OCRResult


class OCRResultRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, ocr_result_id: int) -> OCRResult | None:
        return self.db.get(OCRResult, ocr_result_id)

    def get_latest_for_document(self, document_id: int) -> OCRResult | None:
        stmt = (
            select(OCRResult)
            .where(OCRResult.document_id == document_id)
            .order_by(OCRResult.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_document(self, document_id: int) -> list[OCRResult]:
        stmt = (
            select(OCRResult)
            .where(OCRResult.document_id == document_id)
            .order_by(OCRResult.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def create(
        self,
        *,
        document_id: int,
        engine_name: str,
        page_count: int,
        full_text: str,
        average_confidence: float,
        raw_blocks: list,
        processing_time_ms: int | None,
    ) -> OCRResult:
        ocr_result = OCRResult(
            document_id=document_id,
            engine_name=engine_name,
            page_count=page_count,
            full_text=full_text,
            average_confidence=average_confidence,
            raw_blocks=raw_blocks,
            processing_time_ms=processing_time_ms,
        )
        self.db.add(ocr_result)
        self.db.commit()
        self.db.refresh(ocr_result)
        return ocr_result
