"""audit_rls_hardening

Revision ID: f8g9h0i1j2k3
Revises: e4f5g6h7i8j9
Create Date: 2026-01-16 10:50:00.000000

"""
from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f8g9h0i1j2k3'
down_revision: Union[str, Sequence[str], None] = 'e4f5g6h7i8j9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Implement missing RLS policies for background_jobs and tenant_subscriptions."""
    
    # 1. Background Jobs
    op.execute("ALTER TABLE background_jobs ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY background_jobs_isolation_policy ON background_jobs
        USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::uuid);
    """)

    # 2. Tenant Subscriptions (Fixing missing policy from d2e3f4a5b6c7)
    # The table already has RLS enabled but no policy exists
    op.execute("""
        CREATE POLICY tenant_subscriptions_isolation_policy ON tenant_subscriptions
        USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::uuid);
    """)

    # 3. Discovered Accounts (For multi-cloud org discovery)
    op.execute("ALTER TABLE discovered_accounts ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY discovered_accounts_isolation_policy ON discovered_accounts
        USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::uuid);
    """)


def downgrade() -> None:
    """Drop RLS policies."""
    op.execute("DROP POLICY IF EXISTS background_jobs_isolation_policy ON background_jobs")
    op.execute("DROP POLICY IF EXISTS tenant_subscriptions_isolation_policy ON tenant_subscriptions")
    op.execute("DROP POLICY IF EXISTS discovered_accounts_isolation_policy ON discovered_accounts")
    
    # Note: We keep RLS enabled but polyless (locked down)
