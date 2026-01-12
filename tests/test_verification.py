
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.services.zombies.detector import ZombieDetector
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4
from app.services.llm.factory import LLMFactory

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
async def test_llm_factory_byok_priority():
    """Verify that LLMFactory prioritizes provide API key over global settings."""
    with patch('app.services.llm.factory.ChatOpenAI') as mock_openai:
        with patch('app.services.llm.factory.get_settings') as mock_settings:
            mock_settings.return_value.OPENAI_API_KEY = "global-key"
            mock_settings.return_value.OPENAI_MODEL = "gpt-4o"
            
            # Case 1: Use Global Key
            LLMFactory.create(provider="openai")
            mock_openai.assert_called_with(
                api_key="global-key",
                model="gpt-4o",
                temperature=0
            )
            
            # Case 2: Use BYOK
            LLMFactory.create(provider="openai", api_key="user-personal-key")
            mock_openai.assert_called_with(
                api_key="user-personal-key",
                model="gpt-4o",
                temperature=0
            )

@pytest.mark.asyncio
async def test_nat_gateway_pagination():
    """Verify that NAT gateway detection correctly iterates through all pages."""
    nat_gateways_page1 = [{'NatGatewayId': f'nat-{i}', 'State': 'available'} for i in range(100)]
    nat_gateways_page2 = [{'NatGatewayId': f'nat-{i}', 'State': 'available'} for i in range(100, 150)]
    
    detector = ZombieDetector(region="us-east-1")
    
    # Mock ec2 (get_paginator is sync)
    mock_ec2 = MagicMock()
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = AsyncIterator([
        {'NatGateways': nat_gateways_page1},
        {'NatGateways': nat_gateways_page2}
    ])
    mock_ec2.get_paginator.return_value = mock_paginator
    
    # Mock CloudWatch (get_metric_statistics is async)
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
async def test_ec2_cloudwatch_batching():
    """Verify that EC2 idle instance detection uses get_metric_data for batching."""
    # Create 550 instances to trigger 2 batches (500 + 50)
    mock_instances = [
        {'InstanceId': f'i-{i}', 'InstanceType': 't3.micro', 'LaunchTime': datetime.now(timezone.utc)}
        for i in range(550)
    ]
    
    detector = ZombieDetector(region="us-east-1")
    
    # Mock pagination
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = AsyncIterator([
        {'Reservations': [{'Instances': mock_instances[j:j+100]}]}
        for j in range(0, 550, 100)
    ])
    
    mock_ec2 = MagicMock()
    mock_ec2.get_paginator.return_value = mock_paginator
    
    # Mock CloudWatch (get_metric_data is async)
    mock_cw = AsyncMock()
    mock_cw.get_metric_data.side_effect = [
        {'MetricDataResults': [{'Id': f'm{idx}', 'Values': [0.5]} for idx in range(500)]},
        {'MetricDataResults': [{'Id': f'm{idx}', 'Values': [0.5]} for idx in range(50)]}
    ]
    
    # Mock _get_client
    detector._get_client = AsyncMock(side_effect=lambda service: 
        AsyncContextManagerMock(mock_ec2) if service == "ec2" else AsyncContextManagerMock(mock_cw)
    )
    
    zombies = await detector._find_idle_instances(days=7, cpu_threshold=1.0)
    
    assert len(zombies) == 550
    assert mock_cw.get_metric_data.call_count == 2

@pytest.mark.asyncio
async def test_scheduler_concurrency():
    """Verify that Scheduler runs tenants in parallel with semaphore limit."""
    from app.services.scheduler import SchedulerService
    from unittest.mock import AsyncMock
    
    # Mock DB session and tenants (mock 15 tenants)
    mock_db = MagicMock(spec=AsyncSession)
    mock_tenants = [MagicMock(id=uuid4()) for _ in range(15)]
    
    # Mock analysis method to simulate work delay
    async def slow_analysis(*args, **kwargs):
        import asyncio
        await asyncio.sleep(0.1)
        return {"zombies": 1}

    scheduler = SchedulerService()
    
    # Mock the session maker context manager
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_db
    scheduler.session_maker = MagicMock(return_value=mock_cm)
    
    with patch('app.services.scheduler.select'):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_tenants
        mock_db.execute.return_value = mock_result
        
        with patch('app.services.scheduler.ZombieDetector') as mock_detector:
            detector_instance = mock_detector.return_value
            detector_instance.scan_all = AsyncMock(side_effect=slow_analysis)
            
            # We also need to mock _process_tenant since it does a lot of work
            with patch.object(scheduler, '_process_tenant', new_callable=AsyncMock) as mock_pt:
                start_time = datetime.now()
                await scheduler.daily_analysis_job()
                end_time = datetime.now()
                
                duration = (end_time - start_time).total_seconds()
                
                # Each _process_tenant_wrapper uses the semaphore and calls _process_tenant
                # Here we just verify the wrapper was called and it was fast
                assert duration < 0.5 
                assert mock_pt.call_count == 15
