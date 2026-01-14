"""add_tenant_subscriptions_table

Revision ID: b19f9f39261c
Revises: af06395c042b
Create Date: 2026-01-14 02:52:05.085129

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b19f9f39261c'
down_revision: Union[str, Sequence[str], None] = 'af06395c042b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'tenant_subscriptions',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, unique=True, index=True),
        sa.Column('paystack_customer_code', sa.String(255), nullable=True),
        sa.Column('paystack_subscription_code', sa.String(255), nullable=True),
        sa.Column('paystack_email_token', sa.String(255), nullable=True),
        sa.Column('tier', sa.String(20), nullable=False, server_default='trial'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('next_payment_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('tenant_subscriptions')
