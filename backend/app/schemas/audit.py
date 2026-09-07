"""
Pydantic schemas for the audit log system.
"""
from datetime import datetime

from pydantic import Field

from app.models.document_enums import AuditAction
from app.schemas.base import BaseSchema, TimestampSchema
from app.schemas.user import UserResponse


class AuditLogResponse(TimestampSchema):
    """Full audit log entry as returned by the API."""

    id: int
    action: AuditAction
    user_id: int | None
    document_id: int | None
    details: dict | None
    user: UserResponse | None = None


class AuditLogListResponse(BaseSchema):
    """Paginated list response, mirroring DocumentListResponse's shape."""

    items: list[AuditLogResponse]
    total: int
    skip: int
    limit: int


class AuditLogFilterParams(BaseSchema):
    """
    Query parameters for searching/filtering audit logs. Kept as its
    own schema for the same reason as DocumentFilterParams: a
    self-documenting, easily-extended filtering contract.
    """

    action: AuditAction | None = None
    user_id: int | None = None
    document_id: int | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)
