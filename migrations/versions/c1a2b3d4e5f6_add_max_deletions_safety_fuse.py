"""Add max_deletions_per_hour and simulation_mode safety features

Revision ID: c1a2b3d4e5f6
Revises: bc211fc9da0a
Create Date: 2026-01-13 05:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'b8cca4316ecf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add safety features to remediation_settings."""
    op.add_column(
        'remediation_settings',
        sa.Column('max_deletions_per_hour', sa.Integer(), nullable=False, server_default=sa.text('10'))
    )
    op.add_column(
        'remediation_settings',
        sa.Column('simulation_mode', sa.Boolean(), nullable=False, server_default=sa.text('true'))
    )


def downgrade() -> None:
    """Remove safety feature columns."""
    op.drop_column('remediation_settings', 'simulation_mode')
    op.drop_column('remediation_settings', 'max_deletions_per_hour')
