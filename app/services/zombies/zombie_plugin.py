from abc import ABC, abstractmethod
from typing import List, Dict, Any
import aioboto3

from app.services.pricing.service import PricingService

# Estimated monthly costs (USD) used for zombie resource impact analysis
ESTIMATED_COSTS = {
    "ebs_volume_gb": 0.10,
    "elastic_ip": 3.60,
    "snapshot_gb": 0.05,
    "ec2_t3_micro": 7.50,
    "ec2_t3_small": 15.00,
    "ec2_t3_medium": 30.00,
    "ec2_m5_large": 69.12,
    "ec2_default": 10.00,
    "elb": 20.00,
    "s3_gb": 0.023,
    "ecr_gb": 0.10,
    "sagemaker_endpoint": 108.00,
    "redshift_cluster": 180.00,
    "nat_gateway": 32.40
}

class ZombiePlugin(ABC):
    """
    Abstract base class for Zombie Resource detection plugins.
    Each plugin is responsible for detecting a specific type of zombie resource.
    """

    @property
    @abstractmethod
    def category_key(self) -> str:
        """
        The dictionary key for results (e.g., 'unattached_volumes').
        Used to aggregate results in the final report.
        """
        pass

    @abstractmethod
    async def scan(self, session: aioboto3.Session, region: str, credentials: Dict[str, str] = None) -> List[Dict[str, Any]]:
        """
        Scan for zombie resources.

        Args:
            session: The aioboto3 session to use for client creation.
            region: AWS region to scan.
            credentials: STS credentials dictionary (optional).

        Returns:
            List of dictionaries representing detected zombie resources.
        """
        pass

    async def _get_client(self, session: aioboto3.Session, service_name: str, region: str, credentials: Dict[str, str] = None):
        """Helper to get aioboto3 client with optional credentials."""
        kwargs = {"region_name": region}
        if credentials:
            kwargs.update({
                "aws_access_key_id": credentials["AccessKeyId"],
                "aws_secret_access_key": credentials["SecretAccessKey"],
                "aws_session_token": credentials["SessionToken"],
            })
        return session.client(service_name, **kwargs)
