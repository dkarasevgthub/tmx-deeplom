"""add login attempt table

Revision ID: ac34f0b146ee
Revises: f6cf15475204
Create Date: 2026-08-07 01:24:47.965725

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ac34f0b146ee'
down_revision: Union[str, Sequence[str], None] = 'f6cf15475204'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'login_attempt',
        sa.Column('id', sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column('ip_address', sa.Text, nullable=False),
        sa.Column('email', sa.Text, nullable=False),
        sa.Column('success', sa.Boolean, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.execute("CREATE INDEX login_attempt_ip_idx ON login_attempt (ip_address, created_at DESC);")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('login_attempt_ip_idx', table_name='login_attempt')
    op.drop_table('login_attempt')