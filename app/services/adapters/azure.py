from datetime import datetime
from typing import List, Dict, Any
import structlog
from azure.identity.aio import ClientSecretCredential
from azure.mgmt.costmanagement.aio import CostManagementClient
from azure.mgmt.costmanagement.models import QueryDefinition, QueryTimePeriod, QueryDataset, QueryAggregation, QueryGrouping
from azure.mgmt.resource.resources.aio import ResourceManagementClient

from app.services.adapters.base import BaseAdapter
from app.models.azure_connection import AzureConnection
from app.core.exceptions import AdapterError

logger = structlog.get_logger()

class AzureAdapter(BaseAdapter):
    """
    Azure Cost Management Adapter using official Azure SDK.
    """
    
    def __init__(self, connection: AzureConnection):
        self.connection = connection
        self._credential = None
        self._cost_client = None
        self._resource_client = None

    async def _get_credentials(self):
        if not self._credential:
            self._credential = ClientSecretCredential(
                tenant_id=self.connection.azure_tenant_id,
                client_id=self.connection.client_id,
                client_secret=self.connection.client_secret
            )
        return self._credential

    async def _get_cost_client(self):
        if not self._cost_client:
            creds = await self._get_credentials()
            self._cost_client = CostManagementClient(credential=creds)
        return self._cost_client

    async def _get_resource_client(self):
        if not self._resource_client:
            creds = await self._get_credentials()
            self._resource_client = ResourceManagementClient(
                credential=creds,
                subscription_id=self.connection.subscription_id
            )
        return self._resource_client

    async def verify_connection(self) -> bool:
        """
        Verify Azure Service Principal credentials by attempting to list resource groups.
        """
        try:
            client = await self._get_resource_client()
            async for _ in client.resource_groups.list():
                break
            return True
        except Exception as e:
            logger.error("azure_verify_failed", error=str(e), tenant_id=str(self.connection.tenant_id))
            return False

    async def get_cost_and_usage(
        self,
        start_date: datetime,
        end_date: datetime,
        granularity: str = "DAILY"
    ) -> List[Dict[str, Any]]:
        """
        Fetch Azure costs using the Query API.
        """
        try:
            client = await self._get_cost_client()
            scope = f"/subscriptions/{self.connection.subscription_id}"
            
            query = QueryDefinition(
                type="ActualCost",
                timeframe="Custom",
                time_period=QueryTimePeriod(
                    from_property=start_date,
                    to=end_date
                ),
                dataset=QueryDataset(
                    granularity=granularity.capitalize(),
                    aggregation={
                        "totalCost": QueryAggregation(name="PreTaxCost", function="Sum")
                    },
                    grouping=[
                        QueryGrouping(type="Dimension", name="ResourceGroup"),
                        QueryGrouping(type="Dimension", name="ServiceName")
                    ]
                )
            )
            
            result = await client.query.usage(scope=scope, parameters=query)
            
            # Map Azure columns to standard format
            # Columns usually: [PreTaxCost, ResourceGroup, ServiceName, Currency, UsageDate]
            columns = [col.name for col in result.columns]
            data = []
            for row in result.rows:
                entry = dict(zip(columns, row))
                
                # Parse date if present
                usage_date = entry.get("UsageDate")
                timestamp = datetime.now() # Fallback
                if usage_date:
                    try:
                        timestamp = datetime.strptime(str(usage_date), "%Y-%m-%d")
                    except ValueError:
                        try:
                            timestamp = datetime.fromisoformat(str(usage_date))
                        except Exception:
                            pass

                data.append({
                    "timestamp": timestamp,
                    "service": entry.get("ServiceName", "Unknown"),
                    "region": "global", # Azure Query API grouping by ResourceGroup usually
                    "usage_type": entry.get("ResourceGroup", "Unknown"),
                    "cost_usd": float(entry.get("PreTaxCost", 0)),
                    "currency": entry.get("Currency", "USD"),
                    "amount_raw": float(entry.get("PreTaxCost", 0)),
                    "tags": {"resource_group": entry.get("ResourceGroup")}
                })
            
            return data
        except Exception as e:
            logger.error("azure_cost_fetch_failed", error=str(e), tenant_id=str(self.connection.tenant_id))
            raise AdapterError(f"Azure cost fetch failed: {str(e)}")

    async def discover_resources(self, resource_type: str, region: str = None) -> List[Dict[str, Any]]:
        """
        Discover Azure resources using ResourceManagementClient.
        """
        try:
            client = await self._get_resource_client()
            resources = []
            async for resource in client.resources.list():
                if resource_type and resource_type.lower() not in resource.type.lower():
                    continue
                if region and region.lower() != resource.location.lower():
                    continue
                    
                resources.append({
                    "id": resource.id,
                    "name": resource.name,
                    "type": resource.type,
                    "location": resource.location,
                    "tags": resource.tags
                })
            return resources
        except Exception as e:
            logger.error("azure_resource_discovery_failed", error=str(e))
            return []
