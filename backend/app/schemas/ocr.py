"""
Pydantic schemas for OCR.
"""
from app.schemas.base import BaseSchema, TimestampSchema


class OCRTextBlockSchema(BaseSchema):
    text: str
    confidence: float
    bounding_box: list[list[float]]


class OCRPageSchema(BaseSchema):
    page_number: int
    blocks: list[OCRTextBlockSchema]
    full_text: str
    average_confidence: float


class OCRResultResponse(TimestampSchema):
    id: int
    document_id: int
    engine_name: str
    page_count: int
    full_text: str
    average_confidence: float
    processing_time_ms: int | None
    is_stub_result: bool = False
    # Per-page, per-block detections (text, confidence, bounding box).
    # Stored on the model as a write-once JSONB blob (see
    # app/models/ocr_result.py); exposed here as-is rather than via a
    # nested Pydantic model, since its shape is intentionally an
    # internal storage detail, not a contract this API commits to
    # field-by-field. Consumers that need bounding boxes (e.g. a
    # frontend overlay visualization) read this directly; consumers
    # that only need plain text use `full_text` instead.
    raw_blocks: list = []
    table_data: dict | None = None
    normalized_data: dict | None = None
    validation_results: dict | None = None
    quality_score: dict | None = None
    preprocessing_metadata: dict | None = None


class OCRRunRequest(BaseSchema):
    engine: str | None = None  # defaults to settings.OCR_DEFAULT_ENGINE if omitted
    engine_name: str | None = None  # aliases to engine, kept for backward-compat

class OCREngineStatus(BaseSchema):
    available: bool
    reason: str
    is_production_engine: bool


class OCREngineStatusResponse(BaseSchema):
    engines: dict[str, OCREngineStatus]
    default_engine: str
