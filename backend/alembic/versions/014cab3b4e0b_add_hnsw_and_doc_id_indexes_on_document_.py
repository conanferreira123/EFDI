"""add_hnsw_and_doc_id_indexes_on_document_chunks

Revision ID: 014cab3b4e0b
Revises: 22cf2e444b51
Create Date: 2026-09-16 17:26:03.324232

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '014cab3b4e0b'
down_revision: Union[str, Sequence[str], None] = '22cf2e444b51'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Create HNSW index on document_chunks.embedding using vector_cosine_ops
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw "
            "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64);"
        )
        # Ensure B-tree indexes for document scoping and chunk type filtering exist
        op.execute("CREATE INDEX IF NOT EXISTS ix_document_chunks_document_id ON document_chunks (document_id);")
        op.execute("CREATE INDEX IF NOT EXISTS ix_document_chunks_chunk_type ON document_chunks (chunk_type);")


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw;")
        op.execute("DROP INDEX IF EXISTS ix_document_chunks_document_id;")
        op.execute("DROP INDEX IF EXISTS ix_document_chunks_chunk_type;")

