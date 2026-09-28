"""add_state_json_to_chat_sessions

Revision ID: 2f07f92cbbd1
Revises: 3f80e3e7b361
Create Date: 2026-09-28 17:17:03.756176

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f07f92cbbd1'
down_revision: Union[str, Sequence[str], None] = '3f80e3e7b361'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


from sqlalchemy.dialects import postgresql


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'chat_sessions',
        sa.Column(
            'state_json',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chat_sessions', 'state_json')

