"""
Integration Test: Zombie Scan Flow

Tests the complete zombie scanning flow with mocked AWS services.
Uses moto to mock AWS responses and verifies:
1. Factory correctly passes credentials to detector
2. Detector uses credentials to scan customer's account
3. Plugins correctly identify zombie resources
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from decimal import Decimal
from datetime import datetime, timedelta, timezone

# Test data representing mock AWS resources
MOCK_UNATTACHED_VOLUME = {
    "VolumeId": "vol-test123456",
    "State": "available",
    "Size": 100,
    "VolumeType": "gp3",
    "CreateTime": datetime.now(timezone.utc) - timedelta(days=30),
    "AvailabilityZone": "us-east-1a",
    "Tags": [{"Key": "Name", "Value": "orphaned-vol"}]
}

MOCK_OLD_SNAPSHOT = {
    "SnapshotId": "snap-test789",
    "State": "completed",
    "VolumeSize": 50,
    "StartTime": datetime.now(timezone.utc) - timedelta(days=400),
    "Description": "Old backup",
    "Tags": []
}


class TestZombieDetectorFactory:
    """Test that the factory correctly passes credentials."""

    @pytest.fixture
    def mock_aws_connection(self):
        """Create a mock AWS connection with credentials."""
        connection = MagicMock()
        type(connection).__name__ = "AWSConnection"
        connection.role_arn = "arn:aws:iam::123456789012:role/ValdrixRole"
        connection.external_id = "secure-external-id-123"
        connection.aws_account_id = "123456789012"
        connection.is_verified = True
        return connection

    def test_factory_extracts_aws_credentials(self, mock_aws_connection):
        """Verify factory extracts credentials from AWS connection."""
        from app.services.zombies.factory import ZombieDetectorFactory
        
        # Get detector - should pass credentials
        detector = ZombieDetectorFactory.get_detector(
            connection=mock_aws_connection,
            region="us-east-1",
            db=None
        )
        
        # Verify credentials were passed
        assert detector is not None
        assert hasattr(detector, 'credentials')
        assert detector.credentials["role_arn"] == "arn:aws:iam::123456789012:role/ValdrixRole"
        assert detector.credentials["external_id"] == "secure-external-id-123"
        assert detector.credentials["aws_account_id"] == "123456789012"

    def test_factory_handles_azure_connection(self):
        """Verify factory correctly handles Azure connections."""
        from app.services.zombies.factory import ZombieDetectorFactory
        
        mock_azure = MagicMock()
        type(mock_azure).__name__ = "AzureConnection"
        mock_azure.tenant_id = "azure-tenant-123"
        mock_azure.subscription_id = "azure-sub-456"
        mock_azure.client_id = "azure-client-789"
        
        detector = ZombieDetectorFactory.get_detector(
            connection=mock_azure,
            region="eastus",
            db=None
        )
        
        assert detector is not None

    @patch("google.oauth2.service_account.Credentials.from_service_account_info")
    def test_factory_handles_gcp_connection(self, mock_creds):
        """Verify factory correctly handles GCP connections."""
        mock_creds.return_value = MagicMock()
        from app.services.zombies.factory import ZombieDetectorFactory
        
        mock_gcp = MagicMock()
        type(mock_gcp).__name__ = "GCPConnection"
        mock_gcp.project_id = "my-gcp-project"
        mock_gcp.service_account_json = (
            '{"type": "service_account", "project_id": "my-gcp-project", '
            '"private_key_id": "123", "private_key": "---BEGIN---", '
            '"client_email": "test@gcp.com", "client_id": "123", '
            '"auth_uri": "https://...", "token_uri": "https://...", '
            '"auth_provider_x509_cert_url": "https://...", '
            '"client_x509_cert_url": "https://..."}'
        )
        
        detector = ZombieDetectorFactory.get_detector(
            connection=mock_gcp,
            region="us-central1",
            db=None
        )
        
        # Verify credentials were set
        assert detector is not None
        assert detector.project_id == "my-gcp-project"


class TestZombieScanWithMoto:
    """Integration tests using moto to mock AWS services."""

    @pytest.fixture
    def mock_aws_data(self):
        """Mock data for AWS scans."""
        client = MagicMock()
        client.describe_volumes = AsyncMock(return_value={"Volumes": [MOCK_UNATTACHED_VOLUME]})
        client.describe_snapshots = AsyncMock(return_value={"Snapshots": [MOCK_OLD_SNAPSHOT]})
        client.list_buckets = AsyncMock(return_value={"Buckets": []})
        client.get_metric_data = AsyncMock(return_value={"MetricDataResults": []})
        client.list_objects_v2 = AsyncMock(return_value={"Contents": []})
        client.list_object_versions = AsyncMock(return_value={"Versions": [], "DeleteMarkers": []})

        # Paginator mocks
        async def mock_paginate_volumes(*args, **kwargs):
            yield {"Volumes": [MOCK_UNATTACHED_VOLUME]}
            
        async def mock_paginate_snapshots(*args, **kwargs):
            yield {"Snapshots": [MOCK_OLD_SNAPSHOT]}

        def get_paginator(operation_name):
            p = MagicMock()
            if operation_name == "describe_volumes":
                p.paginate = mock_paginate_volumes
            else:
                p.paginate = mock_paginate_snapshots
            return p

        client.get_paginator.side_effect = get_paginator
        
        # Context manager
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=client)
        mock_ctx.__aexit__ = AsyncMock()
        
        return mock_ctx

    @pytest.mark.asyncio
    async def test_unattached_volume_detection(self, mock_aws_data):
        """Test that unattached volumes are correctly identified as zombies."""
        from app.services.zombies.aws_provider.plugins.storage import UnattachedVolumesPlugin
        
        plugin = UnattachedVolumesPlugin()
        
        # Mock the aioboto3 session
        with patch.object(plugin, '_get_client', new_callable=AsyncMock, return_value=mock_aws_data):
            zombies = await plugin.scan(
                session=MagicMock(),
                region="us-east-1",
                credentials={"aws_account_id": "123456789012"}
            )
        
        # Should detect the unattached volume
        assert len(zombies) > 0

    @pytest.mark.asyncio  
    async def test_old_snapshot_detection(self, mock_aws_data):
        """Test that old snapshots are correctly identified as zombies."""
        from app.services.zombies.aws_provider.plugins.storage import OldSnapshotsPlugin
        
        plugin = OldSnapshotsPlugin()
        
        with patch.object(plugin, '_get_client', new_callable=AsyncMock, return_value=mock_aws_data):
            zombies = await plugin.scan(
                session=MagicMock(),
                region="us-east-1",
                credentials={"aws_account_id": "123456789012"}
            )
        
        assert len(zombies) > 0


class TestPluginRegistry:
    """Test that all plugins are properly registered."""

    def test_aws_plugins_registered(self):
        """Verify AWS plugins are registered."""
        from app.services.zombies.registry import registry
        
        aws_plugins = registry.get_plugins_for_provider("aws")
        assert len(aws_plugins) > 0
        
        # Verify expected plugins exist
        plugin_names = [p.__class__.__name__ for p in aws_plugins]
        assert any("Volume" in name or "Snapshot" in name for name in plugin_names)

    def test_azure_plugins_registered(self):
        """Verify Azure plugins are registered."""
        from app.services.zombies.registry import registry
        
        # Import plugins to trigger registration
        import app.services.zombies.azure_provider.plugins.unattached_disks  # noqa
        import app.services.zombies.azure_provider.plugins.orphaned_ips  # noqa
        import app.services.zombies.azure_provider.plugins.orphaned_images  # noqa
        
        azure_plugins = registry.get_plugins_for_provider("azure")
        assert len(azure_plugins) >= 3

    def test_gcp_plugins_registered(self):
        """Verify GCP plugins are registered."""
        from app.services.zombies.registry import registry
        
        # Import plugins to trigger registration
        import app.services.zombies.gcp_provider.plugins.unattached_disks  # noqa
        import app.services.zombies.gcp_provider.plugins.unused_ips  # noqa
        import app.services.zombies.gcp_provider.plugins.machine_images  # noqa
        
        gcp_plugins = registry.get_plugins_for_provider("gcp")
        assert len(gcp_plugins) >= 3
