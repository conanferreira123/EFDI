"""add training_examples table

Revision ID: b9c2ae51cb79
Revises: bfd7768c6be6
Create Date: 2026-06-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b9c2ae51cb79'
down_revision: Union[str, Sequence[str], None] = 'bfd7768c6be6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('training_examples',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('corrected_by', sa.Integer(), nullable=False),
    sa.Column('task_type', sa.String(length=20), nullable=False),
    sa.Column('document_type', sa.String(length=30), nullable=False),
    sa.Column('source_text', sa.Text(), nullable=False),
    sa.Column('field_key', sa.String(length=50), nullable=True),
    sa.Column('predicted_value', sa.Text(), nullable=True),
    sa.Column('corrected_value', sa.Text(), nullable=False),
    sa.Column('extra_context', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['corrected_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_training_examples_document_id'), 'training_examples', ['document_id'], unique=False)
    op.create_index(op.f('ix_training_examples_task_type'), 'training_examples', ['task_type'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_training_examples_task_type'), table_name='training_examples')
    op.drop_index(op.f('ix_training_examples_document_id'), table_name='training_examples')
    op.drop_table('training_examples')
