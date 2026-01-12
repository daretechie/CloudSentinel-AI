
import pytest
from unittest.mock import MagicMock, AsyncMock
from app.services.zombies.detector import ZombieDetector
from datetime import datetime, timezone, timedelta

class AsyncContextManagerMock:
    def __init__(self, return_value):
        self.return_value = return_value
    async def __aenter__(self):
        return self.return_value
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

class AsyncIterator:
    def __init__(self, items):
        self.items = items
    def __aiter__(self):
        return self
    async def __anext__(self):
        if not self.items:
            raise StopAsyncIteration
        return self.items.pop(0)

@pytest.mark.asyncio
async def test_nat_gateway_pagination():
    """Verify that NAT gateway detection correctly iterates through all pages."""
    # Create 150 mock NAT gateways (requires 2 pages)
    nat_gateways_page1 = [{'NatGatewayId': f'nat-{i}', 'State': 'available'} for i in range(100)]
    nat_gateways_page2 = [{'NatGatewayId': f'nat-{i}', 'State': 'available'} for i in range(100, 150)]
    
    detector = ZombieDetector(region="us-east-1")
    
    # Mock ec2 (Regular MagicMock because get_paginator is sync)
    mock_ec2 = MagicMock()
    mock_paginator = MagicMock()
    
    mock_paginator.paginate.return_value = AsyncIterator([
        {'NatGateways': nat_gateways_page1},
        {'NatGateways': nat_gateways_page2}
    ])
    mock_ec2.get_paginator.return_value = mock_paginator
    
    # Mock CloudWatch (AsyncMock because get_metric_statistics is async)
    mock_cw = AsyncMock()
    mock_cw.get_metric_statistics.return_value = {'Datapoints': [{'Sum': 50}]}

    # Mock _get_client
    detector._get_client = AsyncMock(side_effect=lambda service: 
        AsyncContextManagerMock(mock_ec2) if service == "ec2" else AsyncContextManagerMock(mock_cw)
    )

    zombies = await detector._find_underused_nat_gateways()
    
    assert len(zombies) == 150
    mock_ec2.get_paginator.assert_called_with('describe_nat_gateways')

@pytest.mark.asyncio
async def test_ecr_pagination():
    """Verify that ECR image detection correctly handles pagination."""
    detector = ZombieDetector(region="us-east-1")
    
    # Mock describe_repositories paginator
    repo_paginator = MagicMock()
    repo_paginator.paginate.return_value = AsyncIterator([
        {'repositories': [{'repositoryName': 'repo1'}]}
    ])
    
    # Mock describe_images paginator
    old_date = datetime.now(timezone.utc) - timedelta(days=60)
    image_paginator = MagicMock()
    image_paginator.paginate.return_value = AsyncIterator([
        {'imageDetails': [{'imageDigest': f'sha-{i}', 'imageSizeInBytes': 1000, 'imagePushedAt': old_date} for i in range(100)]},
        {'imageDetails': [{'imageDigest': f'sha-{i}', 'imageSizeInBytes': 1000, 'imagePushedAt': old_date} for i in range(100, 120)]}
    ])
    
    mock_ecr = MagicMock() # Regular MagicMock
    mock_ecr.get_paginator.side_effect = lambda cmd: repo_paginator if cmd == 'describe_repositories' else image_paginator
    
    detector._get_client = AsyncMock(return_value=AsyncContextManagerMock(mock_ecr))
    
    zombies = await detector._find_legacy_ecr_images()
    
    assert len(zombies) == 120
    assert mock_ecr.get_paginator.call_count >= 2
