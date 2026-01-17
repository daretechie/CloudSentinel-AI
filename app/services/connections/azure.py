"""
Azure Connection Service

Handles business logic for Azure Service Principal connections, including:
- Verifying Service Principal access via Azure Identity.
- Coordinating with AzureAdapter for cost/resource validation.
- Managing connection lifecycle.
"""

from uuid import UUID
from datetime import datetime, timezone
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status

from app.models.azure_connection import AzureConnection
from app.services.adapters.azure import AzureAdapter
from app.core.exceptions import AdapterError

logger = structlog.get_logger()

class AzureConnectionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def verify_connection(self, connection_id: UUID, tenant_id: UUID) -> dict:
        """
        Fetch connection, verify Service Principal access, and update status.
        """
        result = await self.db.execute(
            select(AzureConnection).where(
                AzureConnection.id == connection_id,
                AzureConnection.tenant_id == tenant_id
            )
        )
        connection = result.scalar_one_or_none()

        if not connection:
            raise HTTPException(status_code=404, detail="Azure connection not found")

        # Use AzureAdapter for verification
        adapter = AzureAdapter(connection)
        success = await adapter.verify_connection()

        connection.is_active = success
        connection.last_synced_at = datetime.now(timezone.utc)
        
        if success:
            connection.error_message = None
            await self.db.commit()
            logger.info("azure_connection_verified", 
                       connection_id=str(connection_id), 
                       tenant_id=str(tenant_id))
            return {"status": "active", "message": "Azure connection verified successfully"}
        else:
            error_msg = "Verification failed. Please check Client ID, Secret, and Subscription ID."
            connection.error_message = error_msg
            await self.db.commit()
            logger.warning("azure_connection_verification_failed", 
                         connection_id=str(connection_id), 
                         tenant_id=str(tenant_id))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )

    async def list_connections(self, tenant_id: UUID) -> list[AzureConnection]:
        """List all Azure connections for a tenant."""
        result = await self.db.execute(
            select(AzureConnection).where(AzureConnection.tenant_id == tenant_id)
        )
        return list(result.scalars().all())
