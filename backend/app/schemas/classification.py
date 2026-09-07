"""
Pydantic schemas for document classification.
"""
from app.models.document_enums import DocumentType
from app.schemas.base import BaseSchema, TimestampSchema


class ClassificationSignalSchema(BaseSchema):
    matched_text: str
    rule_description: str
    weight: float


class ClassificationResultResponse(TimestampSchema):
    id: int
    document_id: int
    predicted_type: DocumentType
    confidence: float
    engine_name: str
    signals: list[ClassificationSignalSchema]
    scores_by_type: dict[str, float]


class ClassifyRequest(BaseSchema):
    engine: str | None = None  # defaults to "rule_based" if omitted

class ClassifyRequest(BaseSchema):
    engine: str | None = None  # defaults to "rule_based" if omitted


class ClassificationCorrectionRequest(BaseSchema):
    """
    Payload for correcting a wrong classification verdict. corrected_type
    must be a real DocumentType value (UNKNOWN included, in case a
    human determines a document genuinely doesn't fit any of the 9
    known types).
    """
    corrected_type: DocumentType
