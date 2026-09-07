"""
Pydantic schemas for validation.
"""
from app.schemas.base import BaseSchema, TimestampSchema


class ValidationIssueSchema(BaseSchema):
    rule_type: str
    severity: str
    field_key: str | None
    message: str


class ValidationResultResponse(TimestampSchema):
    id: int
    document_id: int
    document_type: str
    engine_name: str
    is_valid: bool
    error_count: int
    warning_count: int
    issues: list[ValidationIssueSchema]


class ValidateRequest(BaseSchema):
    pass  # no parameters currently; reserved for future engine selection
