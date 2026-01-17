"""
Multi-Tenant AWS Adapter (Native Async)

Uses STS AssumeRole to fetch cost data from customer AWS accounts.
Leverages aioboto3 for non-blocking I/O.

Security:
- Never stores long-lived credentials
- Uses temporary credentials that expire in 1 hour
- Each request assumes the customer's IAM role
"""

from typing import List, Dict, Any, Optional, TYPE_CHECKING
from datetime import date, datetime, timezone
from decimal import Decimal
import aioboto3
from botocore.config import Config as BotoConfig

from app.schemas.costs import CloudUsageSummary, CostRecord
from botocore.exceptions import ClientError
import structlog
from app.models.aws_connection import AWSConnection
from app.services.adapters.base import BaseAdapter

if TYPE_CHECKING:
    from app.schemas.costs import CloudUsageSummary

logger = structlog.get_logger()

# Standardized boto config with timeouts to prevent indefinite hangs
# SEC-03: Socket timeouts for all AWS API calls
BOTO_CONFIG = BotoConfig(
    read_timeout=30,
    connect_timeout=10,
    retries={"max_attempts": 3, "mode": "adaptive"}
)

# Safety limit to prevent infinite loops, set to a very high value (300 pages = ~10 years of daily data)
MAX_COST_EXPLORER_PAGES = 300

class MultiTenantAWSAdapter(BaseAdapter):
    """
    AWS adapter that assumes an IAM role in the customer's account using aioboto3.
    """

    def __init__(self, connection: AWSConnection):
        self.connection = connection
        self._credentials: Optional[Dict] = None
        self._credentials_expire_at: Optional[datetime] = None
        self.session = aioboto3.Session()

    async def verify_connection(self) -> bool:
        """Verify that the stored credentials are valid by assuming the role."""
        try:
            await self.get_credentials()
            return True
        except Exception as e:
            logger.error("verify_connection_failed", provider="aws", error=str(e))
            return False

    async def get_credentials(self) -> Dict:
        """Get temporary credentials via STS AssumeRole (Native Async)."""
        if self._credentials and self._credentials_expire_at:
            if datetime.now(timezone.utc) < self._credentials_expire_at:
                return self._credentials

        async with self.session.client("sts") as sts_client:
            try:
                response = await sts_client.assume_role(
                    RoleArn=self.connection.role_arn,
                    RoleSessionName="ValdrixCostFetch",
                    ExternalId=self.connection.external_id,
                    DurationSeconds=3600,
                )

                self._credentials = response["Credentials"]
                self._credentials_expire_at = self._credentials["Expiration"]

                logger.info(
                    "sts_assume_role_success",
                    expires_at=str(self._credentials_expire_at),
                )

                return self._credentials

            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "Unknown")
                logger.error(
                    "sts_assume_role_failed",
                    error=str(e),
                )
                raise AdapterError(
                    message=f"AWS STS AssumeRole failure: {str(e)}",
                    code=error_code,
                ) from e

    async def get_cost_and_usage(
        self,
        start_date: datetime,
        end_date: datetime,
        granularity: str = "DAILY"
    ) -> List[Dict[str, Any]]:
        """Fetch costs using AWS Cost Explorer and normalize."""
        # Note: AWS specific usage_only and group_by_service are not in BaseAdapter interface
        # For base compliance we map to get_daily_costs defaults or we need to expand base
        # But get_cost_and_usage in BaseAdapter returns List[Dict], get_daily_costs returns CloudUsageSummary
        # We need to adapt the return type to List[Dict] as per BaseAdapter or update BaseAdapter to return CloudUsageSummary
        # The BaseAdapter defined earlier returns List[Dict].
        # But `AWSMultiTenantAdapter.get_daily_costs` returns `CloudUsageSummary`.
        # I should probably wrap `get_daily_costs` and return the records list.
        
        summary = await self.get_daily_costs(
            start_date=start_date,
            end_date=end_date,
            granularity=granularity,
            group_by_service=True # Default to detailed breakdown for ingestion
        )
        
        # Convert CostRecord objects to dicts matching BaseAdapter expectation
        return [
            {
                "timestamp": r.date, # CostRecord has date or timestamp
                "service": r.service,
                "region": r.region,
                "usage_type": r.usage_type,
                "cost_usd": r.amount,
                "currency": r.currency,
                "amount_raw": r.amount_raw,
                "tags": {} 
            }
            for r in summary.records
        ]

    async def get_daily_costs(
        self,
        start_date: date,
        end_date: date,
        granularity: str = "DAILY",
        usage_only: bool = False,
        group_by_service: bool = True,
    ) -> CloudUsageSummary:
        """
        Legacy method to fetch costs and return a CloudUsageSummary object.
        Now implemented by consuming the stream_cost_and_usage generator.
        """
        # Convert date to datetime for stream method
        start_dt = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_dt = datetime.combine(end_date, datetime.min.time()).replace(tzinfo=timezone.utc)

        records = []
        total_cost = Decimal("0")

        async for record in self.stream_cost_and_usage(start_dt, end_dt, granularity):
            records.append(CostRecord(
                date=record["timestamp"],
                service=record["service"],
                region=record["region"],
                amount=record["cost_usd"],
                currency=record["currency"],
                amount_raw=record["amount_raw"],
                usage_type=record["usage_type"]
            ))
            total_cost += record["cost_usd"]

        return CloudUsageSummary(
            tenant_id=str(self.connection.tenant_id),
            provider="aws",
            records=records,
            total_cost=total_cost,
            currency="USD",
            start_date=start_date,
            end_date=end_date
        )

    async def stream_cost_and_usage(
        self,
        start_date: datetime,
        end_date: datetime,
        granularity: str = "DAILY"
    ) -> Any:
        """
        Stream cost data from AWS Cost Explorer.
        Optimized to never hold the full dataset in memory.
        """
        creds = await self.get_credentials()

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
                        "Start": start_date.strftime("%Y-%m-%d"),
                        "End": end_date.strftime("%Y-%m-%d"),
                    },
                    "Granularity": granularity,
                    "Metrics": ["AmortizedCost"],
                    "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
                }

                pages_fetched = 0
                while pages_fetched < MAX_COST_EXPLORER_PAGES:
                    response = await client.get_cost_and_usage(**request_params)
                    
                    results_by_time = response.get("ResultsByTime", [])
                    for result in results_by_time:
                        dt = datetime.fromisoformat(result["TimePeriod"]["Start"]).replace(tzinfo=timezone.utc)
                        if "Groups" in result:
                            for group in result["Groups"]:
                                service_name = group["Keys"][0]
                                amount = Decimal(group["Metrics"]["AmortizedCost"]["Amount"])
                                yield {
                                    "timestamp": dt,
                                    "service": service_name,
                                    "region": self.connection.region,
                                    "cost_usd": amount,
                                    "currency": "USD",
                                    "amount_raw": amount,
                                    "usage_type": "Usage"
                                }
                    
                    pages_fetched += 1
                    if "NextPageToken" in response:
                        request_params["NextPageToken"] = response["NextPageToken"]
                    else:
                        break
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "Unknown")
                logger.error("multitenant_cost_fetch_failed", error=str(e))
                from app.core.exceptions import AdapterError
                raise AdapterError(
                    message=f"AWS Cost Explorer failure: {str(e)}",
                    code=error_code,
                    details={"aws_account": self.connection.aws_account_id}
                ) from e

    async def get_gross_usage(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        # Helper that wraps get_daily_costs specifically for gross usage
        summary = await self.get_daily_costs(start_date, end_date, usage_only=True, group_by_service=True)
        # Convert to list of dicts if needed or keep using CloudUsageSummary internally
        # For now, this method signature in original code was somewhat loose or unused in BaseAdapter (not present there)
        # We can keep it or deprecate it.
        return []

    async def discover_resources(self, resource_type: str, region: str = None) -> List[Dict[str, Any]]:
        from app.services.zombies.registry import registry
        plugins = registry.get_plugins_for_provider("aws")
        
        # Simple heuristic to find the right plugin by resource_type
        # e.g. "volume" -> UnattachedVolumesPlugin has reason like "unattached volume"
        # Most plugins have a property we can match on, or we just map them.
        mapping = {
            "volume": "storage",
            "snapshot": "storage",
            "ip": "compute",
            "instance": "compute",
            "load_balancer": "network",
            "nat_gateway": "network",
            "rds": "database",
            "redshift": "database",
            "sagemaker": "analytics",
            "s3": "storage",
            "ecr": "containers",
        }
        
        category = mapping.get(resource_type)
        if not category:
            logger.warning("unsupported_resource_type", resource_type=resource_type)
            return []

        # Find plugin that matches the resource_type in its reason or name
        # For now, to be safe and match legacy behavior exactly without complex logic:
        # We can just check the class name or a new property.
        # But standard registry usage is better.
        
        # Let's filter plugins by category_key
        category_plugins = [p for p in plugins if p.category_key == category]
        
        # Since one category has multiple plugins, we might need a more specific filter
        # or just return all from that category if specifically requested.
        # Legacy behavior was 1:1.
        
        # For now, let's keep it simple: find the first plugin whose class name contains the type
        target_plugin = None
        type_lower = resource_type.lower().replace("_", "")
        for p in plugins:
            if type_lower in p.__class__.__name__.lower():
                target_plugin = p
                break
        
        if not target_plugin:
            logger.warning("plugin_not_found_for_resource", resource_type=resource_type)
            return []

        plugin = target_plugin

        target_region = region or self.connection.region
        creds = await self.get_credentials()
        
        try:
            return await plugin.scan(self.session, target_region, creds)
        except Exception as e:
            logger.error("resource_discovery_failed", 
                         resource_type=resource_type, 
                         region=target_region, 
                         error=str(e))
            return []
