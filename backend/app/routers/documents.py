"""
Document management routes.

Access model:
- Any authenticated user can upload a document (single or bulk).
- FINANCE_ANALYST users can only view/search/delete their own uploads.
- ADMIN, FINANCE_MANAGER, AUDITOR can view/search across all documents
  (oversight roles). Only ADMIN and FINANCE_MANAGER may delete documents
  they didn't upload themselves.
- Folder-scan intake (Phase 10) is ADMIN-only: unlike multipart upload,
  it reads from the server's filesystem rather than from the request
  body, which is a meaningfully different trust boundary.
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_admin
from app.core.exceptions import AuthorizationException, NotFoundException
from app.database.session import get_db
from app.models.document_enums import AuditAction, DocumentStatus, DocumentType
from app.models.roles import UserRole
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import (
    BulkIntakeResponse,
    DocumentFilterParams,
    DocumentListItem,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
    FolderScanRequest,
)
from app.schemas.base import MessageResponse
from app.services.audit_service import AuditService
from app.services.document_service import DocumentService
from app.utils.file_storage import get_file_path, resolve_intake_subpath

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentUploadResponse:
    """Upload a financial document (PDF, PNG, or JPG, up to the configured size limit)."""
    content = await file.read()
    service = DocumentService(db)
    document = service.upload(
        filename=file.filename or "unnamed_upload",
        content_type=file.content_type or "application/octet-stream",
        content=content,
        uploaded_by=current_user,
    )

    AuditService(db).log(
        AuditAction.DOCUMENT_UPLOADED,
        user_id=current_user.id,
        document_id=document.id,
        details={"filename": document.original_filename, "size_bytes": document.file_size_bytes},
    )

    return DocumentUploadResponse(
        id=document.id,
        original_filename=document.original_filename,
        document_type=DocumentType(document.document_type),
        status=DocumentStatus(document.status),
        file_size_bytes=document.file_size_bytes,
    )


@router.post("/upload/bulk", response_model=BulkIntakeResponse, status_code=status.HTTP_201_CREATED)
async def bulk_upload_documents(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BulkIntakeResponse:
    """
    Upload multiple documents in a single multipart request. Any
    authenticated user may use this -- same access model as the
    single-file endpoint above, just batched.

    Partial success by design: one bad file in the batch (wrong type,
    too large, byte-for-byte duplicate of something already uploaded)
    does not prevent the others from being accepted. The response
    reports a per-file outcome so the caller can see exactly which
    files succeeded and which didn't, and why.
    """
    file_tuples = [
        (f.filename or "unnamed_upload", f.content_type or "application/octet-stream", await f.read())
        for f in files
    ]

    service = DocumentService(db)
    results = service.bulk_upload(files=file_tuples, uploaded_by=current_user)

    audit_service = AuditService(db)
    for result in results:
        if result.success:
            audit_service.log(
                AuditAction.DOCUMENT_UPLOADED,
                user_id=current_user.id,
                document_id=result.document_id,
                details={"filename": result.filename, "via": "bulk_upload"},
            )

    succeeded = sum(1 for r in results if r.success)
    return BulkIntakeResponse(
        total_files=len(results), succeeded=succeeded, failed=len(results) - succeeded, results=results,
    )


@router.post(
    "/intake/scan-folder",
    response_model=BulkIntakeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def scan_intake_folder(
    payload: FolderScanRequest = FolderScanRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BulkIntakeResponse:
    """
    Scan a server-side staging folder and ingest every file found
    directly inside it (non-recursive). ADMIN only.

    `payload.subpath`, if given, must be a relative path *within* the
    server's configured intake directory (settings.INTAKE_SCAN_DIR) --
    never an absolute path, never able to escape that root. This is
    fundamentally a different operation from the upload endpoints
    above: those accept bytes the client already sent over HTTP; this
    one has the server read files directly off its own disk, so the
    scannable area is deliberately fixed by server configuration, not
    chosen by the request.
    """
    scan_dir = resolve_intake_subpath(payload.subpath)

    service = DocumentService(db)
    results = service.scan_intake_folder(scan_dir=scan_dir, uploaded_by=current_user)

    audit_service = AuditService(db)
    for result in results:
        if result.success:
            audit_service.log(
                AuditAction.DOCUMENT_UPLOADED,
                user_id=current_user.id,
                document_id=result.document_id,
                details={"filename": result.filename, "via": "folder_scan", "scan_dir": str(scan_dir)},
            )

    succeeded = sum(1 for r in results if r.success)
    return BulkIntakeResponse(
        total_files=len(results), succeeded=succeeded, failed=len(results) - succeeded, results=results,
    )


@router.get("", response_model=DocumentListResponse)
def list_documents(
    document_type: DocumentType | None = None,
    status_filter: DocumentStatus | None = Query(default=None, alias="status"),
    filename: str | None = None,
    uploaded_by: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentListResponse:
    """List/search documents with optional filters. Results are scoped by role (see module docstring)."""
    filters = DocumentFilterParams(
        document_type=document_type,
        status=status_filter,
        filename=filename,
        uploaded_by=uploaded_by,
        date_from=date_from,
        date_to=date_to,
        skip=skip,
        limit=limit,
    )
    service = DocumentService(db)
    results, total = service.search(filters, current_user)
    return DocumentListResponse(
        items=[DocumentListItem.model_validate(d) for d in results],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentResponse:
    """Fetch metadata for a single document."""
    service = DocumentService(db)
    document = service.get_for_user(document_id, current_user)
    return DocumentResponse.model_validate(document)


@router.get("/{document_id}/download")
def download_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Download the original file bytes for a document."""
    service = DocumentService(db)
    document = service.get_for_user(document_id, current_user)

    file_path = get_file_path(document.stored_filename)
    if not file_path.exists():
        raise NotFoundException("Document file on disk", document.stored_filename)

    return FileResponse(
        path=file_path,
        filename=document.original_filename,
        media_type=document.mime_type,
    )


@router.delete("/{document_id}", response_model=MessageResponse)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    """Soft-delete a document (file remains on disk; record is excluded from normal queries)."""
    service = DocumentService(db)
    service.delete(document_id, current_user)

    AuditService(db).log(
        AuditAction.DOCUMENT_DELETED,
        user_id=current_user.id,
        document_id=document_id,
    )

    return MessageResponse(message=f"Document {document_id} deleted successfully")
