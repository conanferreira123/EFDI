"""
Pydantic schemas for the approval workflow.
"""
from app.schemas.base import BaseSchema, TimestampSchema
from app.schemas.user import UserResponse


class WorkflowActionRequest(BaseSchema):
    comment: str | None = None


class WorkflowHistoryResponse(TimestampSchema):
    id: int
    document_id: int
    action: str
    from_status: str
    to_status: str
    comment: str | None
    performed_by: int
    performed_by_user: UserResponse | None = None
