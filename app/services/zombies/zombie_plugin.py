from abc import ABC, abstractmethod
from typing import List, Dict, Any
import aioboto3

# Estimated monthly costs for common resources
ESTIMATED_COSTS = {
    "ebs_volume_gb": 0.10,       # $0.10/GB/month for gp2
    "elastic_ip": 3.65,          # $0.005/hour * 730 hours
    "snapshot_gb": 0.05,         # $0.05/GB/month
    "ec2_t3_micro": 7.59,        # t3.micro monthly
    "ec2_t3_small": 15.18,       # t3.small monthly
    "ec2_t3_medium": 30.37,      # t3.medium monthly
    "ec2_m5_large": 69.12,       # m5.large monthly
    "ec2_default": 30.00,        # Default estimate
    "elb": 16.43,                # ALB base cost
    "s3_gb": 0.023,             # $0.023/GB/month for Standard
    "ecr_gb": 0.10,              # $0.10/GB/month
    "sagemaker_endpoint": 50.00, # Base estimate for idle endpoint
    "redshift_cluster": 180.00,  # Base estimate for dc2.large
    "nat_gateway": 32.00,        # NAT Gateway hourly + processing
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
