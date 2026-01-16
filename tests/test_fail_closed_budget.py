import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4
from decimal import Decimal
from app.services.llm.usage_tracker import UsageTracker
from app.core.exceptions import BudgetExceededError

@pytest.mark.asyncio
async def test_budget_reproduction_fail_closed(db):
    """
    Verifies that if Redis fails, the system FAIL-CLOSED.
    """
    tracker = UsageTracker(db)
    tenant_id = uuid4()
    
    # Mock cache to raise an error
    with patch("app.services.llm.usage_tracker.get_cache_service") as mock_cache_service:
        cache_mock = MagicMock()
        cache_mock.enabled = True
        # Simulate Redis connection error
        cache_mock.client.get.side_effect = Exception("Redis Connection Time-out")
        mock_cache_service.return_value = cache_mock
        
        # In our NEW fail-closed logic, this MUST raise BudgetExceededError
        with pytest.raises(BudgetExceededError) as excinfo:
            await tracker.check_budget(tenant_id)
        
        assert "Fail-Closed" in str(excinfo.value.message)
        assert excinfo.value.status_code == 402
        assert excinfo.value.details["error"] == "service_unavailable"

@pytest.mark.asyncio
async def test_budget_allowed_when_healthy(db):
    """
    Verifies that budgeting still works when system is healthy.
    """
    tracker = UsageTracker(db)
    tenant_id = uuid4()
    
    # Mock cache to be healthy but empty
    with patch("app.services.llm.usage_tracker.get_cache_service") as mock_cache_service:
        cache_mock = MagicMock()
        cache_mock.enabled = True
        cache_mock.client.get.return_value = None
        mock_cache_service.return_value = cache_mock
        
        # Should not raise any error if no budget is set (default)
        await tracker.check_budget(tenant_id)

