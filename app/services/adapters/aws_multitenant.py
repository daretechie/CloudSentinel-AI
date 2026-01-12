"""
Multi-Tenant AWS Adapter (Native Async)

Uses STS AssumeRole to fetch cost data from customer AWS accounts.
Leverages aioboto3 for non-blocking I/O.

Security:
- Never stores long-lived credentials
- Uses temporary credentials that expire in 1 hour
- Each request assumes the customer's IAM role
"""

from typing import List, Dict, Any, Optional
from datetime import date, datetime, timezone
import aioboto3
from botocore.exceptions import ClientError
import structlog
from app.models.aws_connection import AWSConnection
from app.services.adapters.base import CostAdapter

logger = structlog.get_logger()

class MultiTenantAWSAdapter(CostAdapter):
    """
    AWS adapter that assumes an IAM role in the customer's account using aioboto3.
    """
    
    def __init__(self, connection: AWSConnection):
        self.connection = connection
        self._credentials: Optional[Dict] = None
        self._credentials_expire_at: Optional[datetime] = None
        self.session = aioboto3.Session()
    
    async def _get_credentials(self) -> Dict:
        """Get temporary credentials via STS AssumeRole (Native Async)."""
        if self._credentials and self._credentials_expire_at:
            if datetime.now(timezone.utc) < self._credentials_expire_at:
                return self._credentials
        
        async with self.session.client("sts") as sts_client:
            try:
                response = await sts_client.assume_role(
                    RoleArn=self.connection.role_arn,
                    RoleSessionName="CloudSentinelCostFetch",
                    ExternalId=self.connection.external_id,
                    DurationSeconds=3600,
                )
                
                self._credentials = response["Credentials"]
                self._credentials_expire_at = self._credentials["Expiration"]
                
                logger.info(
                    "sts_assume_role_success",
                    role_arn=self.connection.role_arn,
                    expires_at=str(self._credentials_expire_at),
                )
                
                return self._credentials
                
            except ClientError as e:
                logger.error(
                    "sts_assume_role_failed",
                    role_arn=self.connection.role_arn,
                    error=str(e),
                )
                raise

    async def get_daily_costs(
        self, 
        start_date: date, 
        end_date: date,
        usage_only: bool = False,
        group_by_service: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch daily costs using aioboto3 (Native Async)."""
        creds = await self._get_credentials()
        
        async with self.session.client(
            "ce",
            region_name=self.connection.region,
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        ) as client:
            try:
                request_params = {
                    "TimePeriod": {
                        "Start": start_date.isoformat(),
                        "End": end_date.isoformat(),
                    },
                    "Granularity": "DAILY",
                    "Metrics": ["UnblendedCost"],
                }
                
                if usage_only:
                    request_params["Filter"] = {
                        "Dimensions": {"Key": "RECORD_TYPE", "Values": ["Usage"]}
                    }
                
                if group_by_service:
                    request_params["GroupBy"] = [{"Type": "DIMENSION", "Key": "SERVICE"}]
                
                results = []
                response = await client.get_cost_and_usage(**request_params)
                results.extend(response.get("ResultsByTime", []))
                
                while "NextPageToken" in response:
                    request_params["NextPageToken"] = response["NextPageToken"]
                    response = await client.get_cost_and_usage(**request_params)
                    results.extend(response.get("ResultsByTime", []))
                
                logger.info(
                    "multitenant_cost_fetch_success",
                    aws_account=self.connection.aws_account_id,
                    days=len(results),
                )
                return results
                
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "Unknown")
                logger.error("multitenant_cost_fetch_failed", error=str(e))
                return [{"Error": str(e), "Code": error_code}]

    async def get_gross_usage(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        return await self.get_daily_costs(start_date, end_date, usage_only=True, group_by_service=True)
    
    async def get_resource_usage(self, service_name: str) -> List[Dict[str, Any]]:
        return []