"""
Document service: business logic for upload, retrieval, search, and
soft-deletion of financial documents.
"""
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AuthorizationException, FileProcessingException, NotFoundException
from app.models.document_enums import DocumentStatus, DocumentType
from app.models.roles import UserRole
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import BulkIntakeItemResult, DocumentFilterParams
from app.utils.file_storage import (
    compute_sha256,
    delete_file_from_disk,
    detect_mime_type,
    generate_stored_filename,
    list_intake_files,
    save_file,
    validate_upload,
)

logger = logging.getLogger(__name__)


class DocumentService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = DocumentRepository(db)

    def upload(self, *, filename: str, content_type: str, content: bytes, uploaded_by: User):
        extension = validate_upload(
            filename=filename, content_type=content_type, size_bytes=len(content)
        )

        file_hash = compute_sha256(content)
        stored_filename = generate_stored_filename(extension)
        save_file(content, stored_filename)

        document = self.repo.create(
            original_filename=filename,
            stored_filename=stored_filename,
            document_type=DocumentType.UNKNOWN.value,
            status=DocumentStatus.UPLOADED.value,
            file_size_bytes=len(content),
            mime_type=content_type,
            file_hash=file_hash,
            uploaded_by=uploaded_by.id,
        )
        logger.info(
            "Document uploaded: id=%s filename=%s by_user=%s",
            document.id, document.original_filename, uploaded_by.username,
        )
        return document

    def bulk_upload(
        self, *, files: list[tuple[str, str, bytes]], uploaded_by: User
    ) -> list[BulkIntakeItemResult]:
        """
        Upload multiple files in one call. `files` is a list of
        (filename, content_type, content) tuples, mirroring what the
        router extracts from a multipart request.

        Deliberately partial-success: each file is uploaded
        independently inside its own try/except, so one bad file
        (wrong type, oversized, duplicate, corrupted) never aborts
        files that would otherwise have succeeded. The caller gets a
        per-file result list back rather than a single pass/fail for
        the whole batch -- this mirrors the folder-scan intake mode's
        contract exactly, since both are "intake N files, tell me what
        happened to each one."
        """
        results: list[BulkIntakeItemResult] = []

        for filename, content_type, content in files:
            try:
                document = self.upload(
                    filename=filename, content_type=content_type, content=content,
                    uploaded_by=uploaded_by,
                )
                results.append(
                    BulkIntakeItemResult(filename=filename, success=True, document_id=document.id)
                )
            except FileProcessingException as exc:
                logger.warning(
                    "Bulk upload item failed: filename=%s by_user=%s error=%s",
                    filename, uploaded_by.username, exc.message,
                )
                results.append(
                    BulkIntakeItemResult(filename=filename, success=False, error=exc.message)
                )

        return results

    def scan_intake_folder(self, *, scan_dir: Path, uploaded_by: User) -> list[BulkIntakeItemResult]:
        """
        Ingest every allowed-type file found directly inside scan_dir
        (non-recursive -- see list_intake_files). Each file is read
        from disk and run through the same upload() path bulk_upload()
        uses, so intake-folder files and multipart-uploaded files end
        up identical in every way once ingested (same validation, same
        DB row shape, same audit trail).

        Caps at settings.MAX_BULK_INTAKE_FILES regardless of how many
        matching files are actually present in the folder.
        """
        candidate_paths = list_intake_files(scan_dir)

        if len(candidate_paths) > settings.MAX_BULK_INTAKE_FILES:
            logger.warning(
                "Intake folder scan found %s files, exceeding the %s-file limit; "
                "processing only the first %s.",
                len(candidate_paths), settings.MAX_BULK_INTAKE_FILES, settings.MAX_BULK_INTAKE_FILES,
            )
        paths_to_process = candidate_paths[: settings.MAX_BULK_INTAKE_FILES]

        results: list[BulkIntakeItemResult] = []

        for path in paths_to_process:
            filename = path.name
            try:
                content_type = detect_mime_type(path.suffix)
                content = path.read_bytes()
                document = self.upload(
                    filename=filename, content_type=content_type, content=content,
                    uploaded_by=uploaded_by,
                )
                results.append(
                    BulkIntakeItemResult(filename=filename, success=True, document_id=document.id)
                )
            except FileProcessingException as exc:
                logger.warning(
                    "Folder-scan intake item failed: filename=%s path=%s error=%s",
                    filename, path, exc.message,
                )
                results.append(
                    BulkIntakeItemResult(filename=filename, success=False, error=exc.message)
                )
            except OSError as exc:
                # Disk read failure (permissions, file removed mid-scan,
                # etc.) -- a real-world possibility for filesystem-backed
                # intake that a multipart upload could never hit, since
                # the bytes there have already fully arrived over HTTP.
                logger.warning(
                    "Folder-scan intake item failed to read from disk: filename=%s path=%s error=%s",
                    filename, path, exc,
                )
                results.append(
                    BulkIntakeItemResult(filename=filename, success=False, error=f"Could not read file: {exc}")
                )

        return results

    def get_for_user(self, document_id: int, current_user: User):
        """
        Fetch a document, enforcing that FINANCE_ANALYST users may only
        view documents they uploaded themselves. ADMIN, FINANCE_MANAGER,
        and AUDITOR can view any document (auditors and managers need
        oversight across all submissions; admins need full access).
        """
        document = self.repo.get_by_id(document_id)
        if not document:
            raise NotFoundException("Document", document_id)

        if (
            current_user.role == UserRole.FINANCE_ANALYST.value
            and document.uploaded_by != current_user.id
        ):
            raise AuthorizationException("You may only access documents you uploaded")

        return document

    def search(self, filters: DocumentFilterParams, current_user: User):
        """
        FINANCE_ANALYST users are scoped to their own uploads regardless
        of what uploaded_by filter they pass in. Other roles can search
        across all documents and optionally filter by uploader.
        """
        uploaded_by = filters.uploaded_by
        if current_user.role == UserRole.FINANCE_ANALYST.value:
            uploaded_by = current_user.id

        return self.repo.search(
            document_type=filters.document_type.value if filters.document_type else None,
            status=filters.status.value if filters.status else None,
            filename=filters.filename,
            uploaded_by=uploaded_by,
            date_from=filters.date_from,
            date_to=filters.date_to,
            skip=filters.skip,
            limit=filters.limit,
        )

    def delete(self, document_id: int, current_user: User):
        document = self.get_for_user(document_id, current_user)

        if (
            current_user.role == UserRole.FINANCE_ANALYST.value
            and document.uploaded_by != current_user.id
        ):
            raise AuthorizationException("You may only delete documents you uploaded")

        deleted = self.repo.soft_delete(document)
        logger.info("Document soft-deleted: id=%s by_user=%s", document.id, current_user.username)
        return deleted

    def delete_file_bytes(self, document) -> None:
        """
        Physically removes the file from disk. Called separately from
        soft-delete (only by ADMIN, via a dedicated hard-purge path) so
        that the common case (soft-delete) always preserves the file for
        audit/recovery, per enterprise retention practice.
        """
        delete_file_from_disk(document.stored_filename)
