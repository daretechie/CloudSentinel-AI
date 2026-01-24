import pytest
from unittest.mock import MagicMock
from app.modules.optimization.domain.azure_provider.plugins.orphaned_ips import AzureOrphanedIpsPlugin

@pytest.fixture
def plugin():
    return AzureOrphanedIpsPlugin()

@pytest.mark.asyncio
async def test_azure_orphaned_ips_scan(plugin):
    mock_ip = MagicMock()
    mock_ip.id = "/subscriptions/123/ips/my-ip"
    mock_ip.name = "my-ip"
    mock_ip.location = "eastus"
    mock_ip.ip_address = "1.2.3.4"
    mock_ip.ip_configuration = None # Orphaned
    mock_ip.sku.name = "Standard"
    mock_ip.tags = {}
    
    mock_used_ip = MagicMock()
    mock_used_ip.ip_configuration = MagicMock()
    
    class AsyncIter:
        def __init__(self, items):
            self.items = items
        def __aiter__(self):
            return self
        async def __anext__(self):
            if not self.items:
                raise StopAsyncIteration
            return self.items.pop(0)

    mock_client = MagicMock()
    mock_client.public_ip_addresses.list_all.return_value = AsyncIter([mock_ip, mock_used_ip])
    
    results = await plugin.scan(mock_client)
    
    assert len(results) == 1
    assert results[0]["name"] == "my-ip"
    assert results[0]["monthly_waste"] == 3.65
