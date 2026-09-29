"""DocumentChunk Repository.

Handles persistence, deletion, vector similarity search, and native PostgreSQL
full-text search with strict document and user authorization scoping.
"""
from typing import List, Optional
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.roles import UserRole
from app.models.user import User


class ChunkRepository:
    """Data access repository for DocumentChunk entities."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def delete_for_document(self, document_id: int) -> int:
        """Idempotently remove all existing chunks for a document."""
        stmt = delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        result = self.db.execute(stmt)
        return result.rowcount

    def bulk_create(self, chunks: List[DocumentChunk]) -> List[DocumentChunk]:
        """Persist a batch of chunks."""
        if not chunks:
            return []
        self.db.add_all(chunks)
        self.db.flush()
        return chunks

    def get_chunks_for_document(self, document_id: int) -> List[DocumentChunk]:
        """Retrieve all chunks for a document ordered by page and id."""
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.page_number.asc().nulls_first(), DocumentChunk.id.asc())
        )
        return list(self.db.scalars(stmt).all())

    def count_for_document(self, document_id: int) -> int:
        """Count total chunks stored for a document."""
        stmt = select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document_id)
        return self.db.scalar(stmt) or 0

    # -------------------------------------------------------------------------
    # Document-Level Retrieval (Hard Relational Scoping to document_id)
    # -------------------------------------------------------------------------

    def search_vector_for_document(
        self, document_id: int, query_vector: List[float], limit: int = 30
    ) -> List[DocumentChunk]:
        """Dense pgvector cosine distance search scoped strictly to document_id."""
        stmt = (
            select(DocumentChunk)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(
                and_(
                    DocumentChunk.document_id == document_id,
                    Document.is_deleted.is_(False),
                )
            )
            .order_by(DocumentChunk.embedding.cosine_distance(query_vector))
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def search_fts_for_document(
        self, document_id: int, query_text: str, limit: int = 30
    ) -> List[DocumentChunk]:
        """PostgreSQL native Full-Text Search scoped strictly to document_id."""
        clean_q = query_text.strip()
        if not clean_q:
            return []

        # Cover density rank using websearch_to_tsquery
        ts_query = func.websearch_to_tsquery("english", clean_q)
        stmt = (
            select(DocumentChunk)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(
                and_(
                    DocumentChunk.document_id == document_id,
                    Document.is_deleted.is_(False),
                    or_(
                        DocumentChunk.tsv_content.op("@@")(ts_query),
                        DocumentChunk.content.ilike(f"%{clean_q}%"),
                    ),
                )
            )
            .order_by(func.ts_rank_cd(DocumentChunk.tsv_content, ts_query).desc())
            .limit(limit)
        )
        results = list(self.db.scalars(stmt).all())
        return results

    # -------------------------------------------------------------------------
    # Global Corpus Retrieval (Pre-Retrieval In-Database Authorization Scoping)
    # -------------------------------------------------------------------------

    def _apply_authorization_predicates(
        self,
        stmt,
        user: User,
        document_ids: Optional[List[int]] = None,
        section: Optional[str] = None,
        document_type: Optional[str] = None,
        vendor_id: Optional[int] = None,
    ):
        """Inject strict in-database authorization filters and optional metadata pre-filters before retrieval.

        Metadata filters are strictly narrowing constraints combined with AND.
        Never returns unauthorized documents into memory.
        """
        predicates = [Document.is_deleted.is_(False)]

        # If user is FINANCE_ANALYST, strictly scope to documents uploaded by user
        if user.role == UserRole.FINANCE_ANALYST.value:
            predicates.append(Document.uploaded_by == user.id)

        # Optional document_ids filter (for compound SQL + RAG tool queries)
        if document_ids is not None:
            if len(document_ids) == 0:
                # Empty filter should match no documents
                predicates.append(Document.id == -1)
            else:
                predicates.append(Document.id.in_(document_ids))

        # Optional metadata pre-filters (narrowing constraints only)
        if section:
            clean_sec = section.strip()
            predicates.append(
                or_(
                    DocumentChunk.section.ilike(f"%{clean_sec}%"),
                    DocumentChunk.chunk_type.ilike(f"%{clean_sec}%"),
                )
            )

        if document_type:
            clean_type = document_type.strip()
            predicates.append(Document.document_type.ilike(f"%{clean_type}%"))

        if vendor_id is not None:
            from app.models.invoice import Invoice
            vendor_subquery = select(Invoice.document_id).where(Invoice.vendor_id == vendor_id)
            predicates.append(Document.id.in_(vendor_subquery))

        return stmt.join(Document, DocumentChunk.document_id == Document.id).where(and_(*predicates))

    def search_vector_global(
        self,
        query_vector: List[float],
        user: User,
        document_ids: Optional[List[int]] = None,
        section: Optional[str] = None,
        document_type: Optional[str] = None,
        vendor_id: Optional[int] = None,
        limit: int = 30,
    ) -> List[DocumentChunk]:
        """Dense pgvector search across authorized corpus with metadata pre-filtering."""
        stmt = select(DocumentChunk)
        stmt = self._apply_authorization_predicates(
            stmt,
            user=user,
            document_ids=document_ids,
            section=section,
            document_type=document_type,
            vendor_id=vendor_id,
        )
        stmt = stmt.order_by(DocumentChunk.embedding.cosine_distance(query_vector)).limit(limit)
        return list(self.db.scalars(stmt).all())

    def search_fts_global(
        self,
        query_text: str,
        user: User,
        document_ids: Optional[List[int]] = None,
        section: Optional[str] = None,
        document_type: Optional[str] = None,
        vendor_id: Optional[int] = None,
        limit: int = 30,
    ) -> List[DocumentChunk]:
        """PostgreSQL native Full-Text Search across authorized corpus with metadata pre-filtering."""
        clean_q = query_text.strip()
        if not clean_q:
            return []

        ts_query = func.websearch_to_tsquery("english", clean_q)
        stmt = select(DocumentChunk)
        stmt = self._apply_authorization_predicates(
            stmt,
            user=user,
            document_ids=document_ids,
            section=section,
            document_type=document_type,
            vendor_id=vendor_id,
        )
        stmt = stmt.where(
            or_(
                DocumentChunk.tsv_content.op("@@")(ts_query),
                DocumentChunk.content.ilike(f"%{clean_q}%"),
            )
        )
        stmt = stmt.order_by(func.ts_rank_cd(DocumentChunk.tsv_content, ts_query).desc()).limit(limit)
        return list(self.db.scalars(stmt).all())
