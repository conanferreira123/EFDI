"""
Document repository: data-access layer for the Document model.
"""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import Document


class DocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, document_id: int, *, include_deleted: bool = False) -> Document | None:
        stmt = select(Document).where(Document.id == document_id)
        if not include_deleted:
            stmt = stmt.where(Document.is_deleted.is_(False))
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_hash(self, file_hash: str) -> Document | None:
        """
        Returns the single oldest non-deleted document with this hash,
        if any. NOTE: more than one document can legitimately share a
        hash (e.g. the same file uploaded twice, or twice by different
        users) -- this method intentionally returns only the earliest
        one (by id) as "the original," for duplicate-detection messaging.
        Use get_all_by_hash() if every match is needed.
        """
        stmt = (
            select(Document)
            .where(Document.file_hash == file_hash, Document.is_deleted.is_(False))
            .order_by(Document.id.asc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_all_by_hash(self, file_hash: str) -> list[Document]:
        """All non-deleted documents sharing this file hash, oldest first."""
        stmt = (
            select(Document)
            .where(Document.file_hash == file_hash, Document.is_deleted.is_(False))
            .order_by(Document.id.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def create(
        self,
        *,
        original_filename: str,
        stored_filename: str,
        document_type: str,
        status: str,
        file_size_bytes: int,
        mime_type: str,
        file_hash: str,
        uploaded_by: int,
    ) -> Document:
        document = Document(
            original_filename=original_filename,
            stored_filename=stored_filename,
            document_type=document_type,
            status=status,
            file_size_bytes=file_size_bytes,
            mime_type=mime_type,
            file_hash=file_hash,
            uploaded_by=uploaded_by,
        )
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        return document

    def search(
        self,
        *,
        document_type: str | None = None,
        status: str | None = None,
        filename: str | None = None,
        uploaded_by: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Document], int]:
        """
        Returns (page_of_results, total_matching_count). The count query
        mirrors the same filters so pagination metadata is accurate.
        """
        conditions = [Document.is_deleted.is_(False)]

        if document_type:
            conditions.append(Document.document_type == document_type)
        if status:
            conditions.append(Document.status == status)
        if filename:
            conditions.append(Document.original_filename.ilike(f"%{filename}%"))
        if uploaded_by is not None:
            conditions.append(Document.uploaded_by == uploaded_by)
        if date_from:
            conditions.append(Document.created_at >= date_from)
        if date_to:
            conditions.append(Document.created_at <= date_to)

        count_stmt = select(func.count()).select_from(Document).where(*conditions)
        total = self.db.execute(count_stmt).scalar_one()

        stmt = (
            select(Document)
            .where(*conditions)
            .order_by(Document.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        results = list(self.db.execute(stmt).scalars().all())

        return results, total

    def soft_delete(self, document: Document) -> Document:
        document.is_deleted = True
        self.db.commit()
        self.db.refresh(document)
        return document

    def update_status(self, document: Document, status: str) -> Document:
        document.status = status
        self.db.commit()
        self.db.refresh(document)
        return document
