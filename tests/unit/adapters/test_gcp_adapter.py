import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch
from app.services.adapters.gcp import GCPAdapter
from app.models.gcp_connection import GCPConnection

@pytest.fixture
def mock_gcp_connection():
    return GCPConnection(
        project_id="test-project",
        billing_project_id="billing-project",
        billing_dataset="billing_dataset",
        billing_table="billing_table",
        service_account_json='{"type": "service_account", "project_id": "test-project"}'
    )

@pytest.mark.asyncio
async def test_gcp_adapter_verify_connection(mock_gcp_connection):
    with patch("google.cloud.bigquery.Client") as mock_bq_client:
        mock_client_inst = mock_bq_client.return_value
        mock_client_inst.list_datasets.return_value = [MagicMock()]
        
        adapter = GCPAdapter(mock_gcp_connection)
        is_verified = await adapter.verify_connection()
        
        assert is_verified is True
        # Verify it checks the billing project if provided
        mock_client_inst.list_datasets.assert_called_once_with(project="billing-project", max_results=1)

@pytest.mark.asyncio
async def test_gcp_adapter_get_cost_and_usage(mock_gcp_connection):
    with patch("google.cloud.bigquery.Client") as mock_bq_client:
        mock_client_inst = mock_bq_client.return_value
        mock_row = MagicMock()
        mock_row.timestamp = datetime(2026, 1, 1)
        mock_row.service = "Compute Engine"
        mock_row.cost_usd = 10.5
        mock_row.currency = "USD"
        
        mock_job = MagicMock()
        mock_job.result.return_value = [mock_row]
        mock_client_inst.query.return_value = mock_job
        
        adapter = GCPAdapter(mock_gcp_connection)
        costs = await adapter.get_cost_and_usage(datetime(2026, 1, 1), datetime(2026, 1, 2))
        
        assert len(costs) == 1
        assert costs[0]["service"] == "Compute Engine"
        assert costs[0]["cost_usd"] == 10.5
        
        # Verify query path
        tokenized_query = mock_client_inst.query.call_args[0][0]
        assert "billing-project.billing_dataset.billing_table" in tokenized_query

@pytest.mark.asyncio
async def test_gcp_adapter_discover_resources(mock_gcp_connection):
    with patch("google.cloud.asset_v1.AssetServiceClient") as mock_asset_client:
        mock_client_inst = mock_asset_client.return_value
        
        mock_asset = MagicMock()
        mock_asset.name = "//compute.googleapis.com/projects/test-project/zones/us-central1-a/instances/test-instance"
        mock_asset.asset_type = "compute.googleapis.com/Instance"
        mock_asset.resource.data = {"status": "RUNNING"}
        
        mock_client_inst.list_assets.return_value = [mock_asset]
        
        adapter = GCPAdapter(mock_gcp_connection)
        resources = await adapter.discover_resources("compute")
        
        assert len(resources) == 1
        assert resources[0]["name"] == "test-instance"
        assert resources[0]["type"] == "compute.googleapis.com/Instance"
