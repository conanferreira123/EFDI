"""
Pydantic schemas for documents.
"""
from datetime import datetime

from pydantic import Field

from app.models.document_enums import DocumentStatus, DocumentType
from app.schemas.base import BaseSchema, TimestampSchema
from app.schemas.user import UserResponse


class DocumentResponse(TimestampSchema):
    """Full document representation returned by the API."""

    id: int
    original_filename: str
    document_type: DocumentType
    status: DocumentStatus
    file_size_bytes: int
    mime_type: str
    file_hash: str
    page_count: int | None
    uploaded_by: int
    uploaded_by_user: UserResponse | None = None


class DocumentListItem(BaseSchema):
    """
    Lighter-weight representation for list/search results, omitting
    fields not useful in a table view (hash, full uploader profile).
    """

    id: int
    original_filename: str
    document_type: DocumentType
    status: DocumentStatus
    file_size_bytes: int
    mime_type: str
    uploaded_by: int
    created_at: datetime


class DocumentListResponse(BaseSchema):
    """Paginated list response."""

    items: list[DocumentListItem]
    total: int
    skip: int
    limit: int


class DocumentUploadResponse(BaseSchema):
    """Returned immediately after a successful upload."""

    id: int
    original_filename: str
    document_type: DocumentType
    status: DocumentStatus
    file_size_bytes: int
    message: str = "Document uploaded successfully"


class DocumentFilterParams(BaseSchema):
    """
    Query parameters for searching/filtering documents.

    Kept as its own schema (rather than loose function params) so the
    filtering contract is self-documenting and easy to extend in later
    phases without changing every call site.
    """

    document_type: DocumentType | None = None
    status: DocumentStatus | None = None
    filename: str | None = Field(default=None, description="Case-insensitive substring match")
    uploaded_by: int | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)


class BulkIntakeItemResult(BaseSchema):
    """
    Outcome for a single file within a bulk-upload or folder-scan
    intake request. Bulk intake is deliberately partial-success: one
    bad file (wrong type, oversized, corrupted) must never abort the
    whole batch, so every item gets its own success/failure record
    rather than the endpoint failing the entire request on the first
    error.
    """

    filename: str
    success: bool
    document_id: int | None = None
    error: str | None = None


class BulkIntakeResponse(BaseSchema):
    """Aggregate result of a bulk-upload or folder-scan intake request."""

    total_files: int
    succeeded: int
    failed: int
    results: list[BulkIntakeItemResult]


class FolderScanRequest(BaseSchema):
    """
    Payload for the folder-scan intake endpoint.

    `subpath` is optional and, if given, must be a relative path
    *within* the server's configured intake directory (see
    settings.INTAKE_SCAN_DIR) -- never an absolute path and never
    containing '..' segments. See
    app/utils/file_storage.py:resolve_intake_subpath for the
    enforcement of that boundary.
    """

    subpath: str | None = Field(
        default=None,
        description="Relative subfolder within the server's configured intake directory to scan. Omit to scan the intake root itself.",
    )
