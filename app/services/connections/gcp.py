"""
GCP Connection Service

Handles business logic for GCP connections, including:
- Verifying Service Account access.
- Verifying Workload Identity Federation (OIDC) trust.
- Managing connection lifecycle.
"""

from uuid import UUID
from datetime import datetime, timezone
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status

from app.models.gcp_connection import GCPConnection
from app.services.adapters.gcp import GCPAdapter
from app.services.connections.oidc import OIDCService

logger = structlog.get_logger()

class GCPConnectionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def verify_connection(self, connection_id: UUID, tenant_id: UUID) -> dict:
        """
        Fetch connection, verify access (SA or OIDC), and update status.
        """
        result = await self.db.execute(
            select(GCPConnection).where(
                GCPConnection.id == connection_id,
                GCPConnection.tenant_id == tenant_id
            )
        )
        connection = result.scalar_one_or_none()

        if not connection:
            raise HTTPException(status_code=404, detail="GCP connection not found")

        success = False
        error_msg = None

        if connection.auth_method == "secret":
            # Verify via GCPAdapter (Service Account)
            adapter = GCPAdapter(connection)
            success = await adapter.verify_connection()
            if not success:
                error_msg = "Service Account verification failed."
        else:
            # Verify via OIDCService (Workload Identity)
            success, error_msg = await OIDCService.verify_gcp_access(
                str(tenant_id), connection.project_id
            )

        connection.is_active = success
        connection.last_synced_at = datetime.now(timezone.utc)
        
        if success:
            connection.error_message = None
            await self.db.commit()
            logger.info("gcp_connection_verified", 
                       connection_id=str(connection_id), 
                       tenant_id=str(tenant_id),
                       method=connection.auth_method)
            return {"status": "active", "message": "GCP connection verified successfully"}
        else:
            connection.error_message = error_msg
            await self.db.commit()
            logger.warning("gcp_connection_verification_failed", 
                         connection_id=str(connection_id), 
                         tenant_id=str(tenant_id),
                         error=error_msg)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg or "GCP verification failed."
            )
