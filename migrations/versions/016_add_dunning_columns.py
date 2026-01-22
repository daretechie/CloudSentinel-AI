"""Add dunning columns to tenant_subscriptions

Revision ID: 016_add_dunning_columns
Revises: 015_previous
Create Date: 2026-01-21
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '016_add_dunning_columns'
down_revision: Union[str, None] = 'ef16c5660eba'  # Previous head
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add dunning tracking columns to tenant_subscriptions."""
    op.add_column(
        'tenant_subscriptions',
        sa.Column('dunning_attempts', sa.Integer(), nullable=False, server_default='0')
    )
    op.add_column(
        'tenant_subscriptions',
        sa.Column('last_dunning_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'tenant_subscriptions',
        sa.Column('dunning_next_retry_at', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Remove dunning columns from tenant_subscriptions."""
    op.drop_column('tenant_subscriptions', 'dunning_next_retry_at')
    op.drop_column('tenant_subscriptions', 'last_dunning_at')
    op.drop_column('tenant_subscriptions', 'dunning_attempts')
