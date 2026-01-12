"""Add preferred_provider and preferred_model

Revision ID: 796761939f88
Revises: bd68bb6c3d14
Create Date: 2026-01-11 08:02:36.412659

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '796761939f88'
down_revision: Union[str, Sequence[str], None] = 'bd68bb6c3d14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('llm_budgets', sa.Column('preferred_provider', sa.String(length=50), nullable=False, server_default='groq'))
    op.add_column('llm_budgets', sa.Column('preferred_model', sa.String(length=100), nullable=False, server_default='llama-3.3-70b-versatile'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('llm_budgets', 'preferred_model')
    op.drop_column('llm_budgets', 'preferred_provider')
