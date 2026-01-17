import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from uuid import uuid4
from decimal import Decimal
from app.services.llm.usage_tracker import UsageTracker
from app.core.exceptions import BudgetExceededError

@pytest.mark.asyncio
async def test_budget_reproduction_fail_closed(db):
    """
    Verifies that if Redis fails, the system FAIL-CLOSED.
    """
    # Patch session methods to avoid transaction conflicts in tests
    class MockAsyncContext:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False

    db.commit = AsyncMock(side_effect=db.flush)
    db.rollback = AsyncMock()
    db.begin = MagicMock(return_value=MockAsyncContext())
    db.begin_nested = MagicMock(return_value=MockAsyncContext())

    tracker = UsageTracker(db)
    tenant_id = uuid4()
    
    import sqlalchemy as sa
    await db.execute(sa.text(f"SELECT set_config('app.current_tenant_id', '{tenant_id}', true)"))
    
    # Mock cache to raise an error
    with patch("app.services.llm.usage_tracker.get_cache_service") as mock_cache_service:
        cache_mock = MagicMock()
        cache_mock.enabled = True
        cache_mock.client.get = AsyncMock(side_effect=Exception("Redis Connection Time-out"))
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
    # Patch session to avoid transaction conflicts
    db.commit = AsyncMock(side_effect=db.flush)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock()
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    db.begin = MagicMock(return_value=mock_ctx)
    db.begin_nested = MagicMock(return_value=mock_ctx)

    tracker = UsageTracker(db)
    tenant_id = uuid4()
    
    import sqlalchemy as sa
    await db.execute(sa.text(f"SELECT set_config('app.current_tenant_id', '{tenant_id}', true)"))
    
    # Mock cache to be healthy but empty
    with patch("app.services.llm.usage_tracker.get_cache_service") as mock_cache_service:
        cache_mock = MagicMock()
        cache_mock.enabled = True
        cache_mock.client.get = AsyncMock(return_value=None)
        mock_cache_service.return_value = cache_mock

        
        # Should not raise any error if no budget is set (default)
        await tracker.check_budget(tenant_id)

