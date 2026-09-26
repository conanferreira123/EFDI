"""add_document_user_activity_table

Revision ID: 3f80e3e7b361
Revises: 361bf56d16a1
Create Date: 2026-09-26 23:09:50.101411

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f80e3e7b361'
down_revision: Union[str, Sequence[str], None] = '361bf56d16a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'document_user_activity',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'document_id', name='uq_document_user_activity_user_doc'),
    )
    op.create_index(op.f('ix_document_user_activity_user_id'), 'document_user_activity', ['user_id'], unique=False)
    op.create_index(op.f('ix_document_user_activity_document_id'), 'document_user_activity', ['document_id'], unique=False)
    op.create_index('ix_document_user_activity_user_last_activity', 'document_user_activity', ['user_id', 'last_activity_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_document_user_activity_user_last_activity', table_name='document_user_activity')
    op.drop_index(op.f('ix_document_user_activity_document_id'), table_name='document_user_activity')
    op.drop_index(op.f('ix_document_user_activity_user_id'), table_name='document_user_activity')
    op.drop_table('document_user_activity')
