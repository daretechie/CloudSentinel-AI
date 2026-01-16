import json
from datetime import datetime
from typing import List, Dict, Any
import structlog
from google.cloud import bigquery
from google.cloud import asset_v1
from google.oauth2 import service_account

from app.services.adapters.base import BaseAdapter
from app.models.gcp_connection import GCPConnection

logger = structlog.get_logger()

class GCPAdapter(BaseAdapter):
    """
    Google Cloud Platform Adapter using BigQuery for costs and Cloud Asset Inventory for resources.
    
    Standard industry practice for GCP FinOps is to export billing data to BigQuery.
    """
    
    def __init__(self, connection: GCPConnection):
        self.connection = connection
        self._credentials = self._get_credentials()

    def _get_credentials(self):
        """Initialize GCP credentials from service account JSON or environment."""
        if self.connection.service_account_json:
            try:
                info = json.loads(self.connection.service_account_json)
                return service_account.Credentials.from_service_account_info(info)
            except Exception as e:
                logger.error("gcp_credentials_load_error", error=str(e))
        return None  # Fallback to default credentials

    def _get_bq_client(self):
        return bigquery.Client(
            project=self.connection.project_id,
            credentials=self._credentials
        )

    def _get_asset_client(self):
        return asset_v1.AssetServiceClient(credentials=self._credentials)

    async def verify_connection(self) -> bool:
        """Verify GCP credentials by attempting to list projects or a lightweight check."""
        try:
            client = self._get_bq_client()
            # Just a simple check - list datasets in the billing project
            billing_project = self.connection.billing_project_id or self.connection.project_id
            list(client.list_datasets(project=billing_project, max_results=1))
            return True
        except Exception as e:
            logger.error("gcp_connection_verify_failed", error=str(e))
            return False

    async def get_cost_and_usage(
        self,
        start_date: datetime,
        end_date: datetime,
        granularity: str = "DAILY"
    ) -> List[Dict[str, Any]]:
        """
        Fetch GCP costs from BigQuery billing export.
        """
        if not self.connection.billing_dataset or not self.connection.billing_table:
            logger.warning("gcp_bq_export_not_configured", project_id=self.connection.project_id)
            return []

        client = self._get_bq_client()
        
        # Determine the table path
        billing_project = self.connection.billing_project_id or self.connection.project_id
        table_path = f"{billing_project}.{self.connection.billing_dataset}.{self.connection.billing_table}"

        # Standard GCP Billing Export Query
        query = f"""
            SELECT
                service.description as service,
                SUM(cost) as cost_usd,
                MAX(currency) as currency,
                TIMESTAMP_TRUNC(usage_start_time, DAY) as timestamp
            FROM `{table_path}`
            WHERE usage_start_time >= @start_date
              AND usage_start_time <= @end_date
            GROUP BY service, timestamp
            ORDER BY timestamp DESC
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "TIMESTAMP", start_date),
                bigquery.ScalarQueryParameter("end_date", "TIMESTAMP", end_date),
            ]
        )

        try:
            query_job = client.query(query, job_config=job_config)
            results = query_job.result()
            
            return [
                {
                    "timestamp": row.timestamp,
                    "service": row.service,
                    "cost_usd": float(row.cost_usd),
                    "currency": row.currency,
                    "region": "global" # Detailed region usually needs separate field mapping
                }
                for row in results
            ]
        except Exception as e:
            logger.error("gcp_bq_query_failed", table=table_path, error=str(e))
            return []

    async def discover_resources(self, resource_type: str, region: str = None) -> List[Dict[str, Any]]:
        """
        Discover GCP resources using Cloud Asset API.
        """
        client = self._get_asset_client()
        parent = f"projects/{self.connection.project_id}"
        
        # Map generic resource types to GCP content types
        asset_types = []
        if resource_type == "compute":
            asset_types = ["compute.googleapis.com/Instance"]
        elif resource_type == "storage":
            asset_types = ["storage.googleapis.com/Bucket"]
        
        try:
            response = client.list_assets(
                request={
                    "parent": parent,
                    "asset_types": asset_types,
                    "content_type": asset_v1.ContentType.RESOURCE,
                }
            )
            
            resources = []
            for asset in response:
                res = asset.resource
                resources.append({
                    "id": asset.name,
                    "name": asset.name.split("/")[-1],
                    "type": asset.asset_type,
                    "region": region or "global",
                    "provider": "gcp",
                    "metadata": {
                        "project_id": self.connection.project_id,
                        "data": str(res.data)
                    }
                })
            return resources
        except Exception as e:
            logger.error("gcp_discovery_failed", error=str(e))
            return []
