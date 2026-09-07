"""DocumentChunk model.

Stores semantic chunks of documents (e.g. headers, line items, summaries)
with 384-dimensional embeddings for similarity search and retrieval.
"""
from sqlalchemy import ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.database.base import Base, TimestampMixin


class DocumentChunk(Base, TimestampMixin):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)  # HEADER, LINE_ITEMS, SUMMARY
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(
        JSONB, nullable=True, server_default=text("'{}'::jsonb")
    )

    document = relationship("Document", back_populates="document_chunks", lazy="joined")

    def __repr__(self) -> str:
        return (
            f"<DocumentChunk id={self.id} document_id={self.document_id} "
            f"type={self.chunk_type} page={self.page_number}>"
        )
