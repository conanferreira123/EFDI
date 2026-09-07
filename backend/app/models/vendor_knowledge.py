"""VendorKnowledge model.

Stores searchable vendor information together with a 384-dimensional
embedding vector for semantic lookup.
"""

from sqlalchemy import Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.database.base import Base, TimestampMixin


class VendorKnowledge(Base, TimestampMixin):
    __tablename__ = "vendor_knowledge"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    vendor_code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    vendor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tax_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    default_gl_account: Mapped[str | None] = mapped_column(String(30), nullable=True)
    default_cost_center: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Full-text searchable field (e.g., concatenated name + description)
    search_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Embedding for semantic search
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)

    # Optional extra JSON data (e.g., address, contact details)
    metadata_json: Mapped[dict] = mapped_column(
        JSONB, nullable=True, server_default=text("'{}'::jsonb")
    )

    def __repr__(self) -> str:
        return f"<VendorKnowledge id={self.id} code={self.vendor_code} name={self.vendor_name}>"
