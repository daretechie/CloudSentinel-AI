from typing import Any
from app.services.zombies.base import BaseZombieDetector
from app.services.zombies.aws_provider.detector import AWSZombieDetector
from app.services.zombies.azure_provider.detector import AzureZombieDetector
from app.services.zombies.gcp_provider.detector import GCPZombieDetector
from app.models.aws_connection import AWSConnection
from app.models.azure_connection import AzureConnection
from app.models.gcp_connection import GCPConnection

class ZombieDetectorFactory:
    """
    Factory to instantiate the correct ZombieDetector based on connection type.
    """
    from sqlalchemy.ext.asyncio import AsyncSession
    @staticmethod
    def get_detector(connection: Any, region: str = "us-east-1", db: AsyncSession = None) -> BaseZombieDetector:
        type_name = type(connection).__name__
        
        if "AWSConnection" in type_name:
            creds = {
                "role_arn": getattr(connection, "role_arn", None),
                "external_id": getattr(connection, "external_id", None),
                "aws_account_id": getattr(connection, "aws_account_id", None),
            }
            return AWSZombieDetector(region=region, credentials=creds, db=db)
            
        elif "AzureConnection" in type_name:
            creds = {
                "tenant_id": getattr(connection, "azure_tenant_id", None),
                "client_id": getattr(connection, "client_id", None),
                "client_secret": getattr(connection, "client_secret", None),
                "subscription_id": getattr(connection, "subscription_id", None)
            }
            return AzureZombieDetector(region="global", credentials=creds, db=db)
            
        elif "GCPConnection" in type_name:
            creds = {
                "project_id": getattr(connection, "project_id", None),
                "service_account_json": getattr(connection, "service_account_json", None),
                "auth_method": getattr(connection, "auth_method", "secret")
            }
            return GCPZombieDetector(region="global", credentials=creds, db=db)
            
        raise ValueError(f"Unsupported connection type: {type_name}")
