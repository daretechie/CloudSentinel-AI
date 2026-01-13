"""Add tenant_subscriptions table for Stripe billing

Revision ID: d2e3f4a5b6c7
Revises: c1a2b3d4e5f6
Create Date: 2026-01-13 05:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'c1a2b3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create tenant_subscriptions table for Stripe billing."""
    op.create_table(
        'tenant_subscriptions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('stripe_customer_id', sa.String(255), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(255), nullable=True),
        sa.Column('tier', sa.String(20), nullable=False, server_default='free'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(
            ['tenant_id'], ['tenants.id'],
            name=op.f('fk_tenant_subscriptions_tenant_id_tenants'),
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_tenant_subscriptions')),
        sa.UniqueConstraint('tenant_id', name=op.f('uq_tenant_subscriptions_tenant_id'))
    )
    op.create_index(
        op.f('ix_tenant_subscriptions_tenant_id'),
        'tenant_subscriptions',
        ['tenant_id'],
        unique=False
    )
    op.create_index(
        op.f('ix_tenant_subscriptions_stripe_customer_id'),
        'tenant_subscriptions',
        ['stripe_customer_id'],
        unique=False
    )

    # Enable RLS on new table
    op.execute("ALTER TABLE tenant_subscriptions ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Drop tenant_subscriptions table."""
    op.drop_index(op.f('ix_tenant_subscriptions_stripe_customer_id'),
                  table_name='tenant_subscriptions')
    op.drop_index(op.f('ix_tenant_subscriptions_tenant_id'),
                  table_name='tenant_subscriptions')
    op.drop_table('tenant_subscriptions')
