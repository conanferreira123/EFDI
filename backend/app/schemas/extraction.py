"""
Pydantic schemas for data extraction.
"""
from typing import Any
from pydantic import computed_field
from app.schemas.base import BaseSchema, TimestampSchema


class ExtractedFieldSchema(BaseSchema):
    value: Any = None
    confidence: float
    matched_text: str | None = None
    is_found: bool
    provenance: str | None = None
    conflict_value: str | None = None


class ExtractionResultResponse(TimestampSchema):
    id: int
    document_id: int
    document_type: str
    engine_name: str
    fields: dict[str, ExtractedFieldSchema]
    overall_confidence: float
    fields_found_count: int
    fields_total_count: int

    @computed_field
    @property
    def canonical(self) -> dict[str, Any] | None:
        """Expose the canonical hierarchical structure for NPO documents when available."""
        if self.document_type == "NPO" and "canonical" in self.fields:
            return self.fields["canonical"].value
        return None


class ExtractRequest(BaseSchema):
    engine: str | None = None  # defaults to settings.EXTRACTION_DEFAULT_ENGINE if omitted
    engine_name: str | None = None  # alias for backward-compatibility


class FieldUpdateRequest(BaseSchema):
    """
    Payload for manually correcting/filling a single field after
    extraction -- the future review UI's "fill in the nulls" action.
    Marks the field as manually-entered with full confidence, since a
    human explicitly provided the value.
    """
    value: str
