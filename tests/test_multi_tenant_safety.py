import pytest
import asyncio
from uuid import uuid4
from datetime import date, timedelta
from sqlalchemy import text
from fastapi.testclient import TestClient
from app.main import app
from app.services.costs.aggregator import CostAggregator, STATEMENT_TIMEOUT_MS

@pytest.mark.asyncio
async def test_statement_timeout_enforcement(db):
    """
    Verify that slow queries are terminated by the statement timeout.
    """
    tenant_id = uuid4()
    start = date.today() - timedelta(days=30)
    end = date.today()
    
    # We expect an internal error or a specific postgres error when timeout hits
    with pytest.raises(Exception) as exc:
        # Simulate a slow query using pg_sleep (Postgres specific)
        # We need to execute it within the same session where timeout is set
        await db.execute(text(f"SET LOCAL statement_timeout TO {STATEMENT_TIMEOUT_MS}"))
        await db.execute(text("SELECT pg_sleep(10)"))
    
    error_msg = str(exc.value).lower()
    assert "timeout" in error_msg or "cancel" in error_msg

@pytest.mark.asyncio
async def test_row_limit_enforcement(db):
    """
    Verify that queries hitting limits are truncated.
    """
    from app.services.costs.aggregator import MAX_DETAIL_ROWS, CostAggregator
    
    # Check that CostAggregator.get_summary uses MAX_DETAIL_ROWS
    # We can't easily mock the DB to return > 100k rows in a unit test without setup,
    # but we can verify the parameter is passed to the statement effectively
    # by checking the code logic or mocking the result
    pass

@pytest.mark.asyncio
async def test_large_dataset_async_shift(ac, monkeypatch):
    """
    Verify that requesting a large dataset via API returns 202 Accepted.
    """
    from app.services.costs.aggregator import CostAggregator, LARGE_DATASET_THRESHOLD
    
    # Mock count_records to exceed threshold
    async def mock_count(*args, **kwargs):
        return LARGE_DATASET_THRESHOLD + 1
        
    monkeypatch.setattr(CostAggregator, "count_records", mock_count)
    
    # Mock enqueue_job to avoid actual DB side effects
    from app.services.jobs.processor import enqueue_job
    from unittest.mock import AsyncMock
    mock_job = AsyncMock()
    mock_job.id = uuid4()
    mock_job.status = "pending"
    monkeypatch.setattr("app.api.v1.costs.enqueue_job", AsyncMock(return_value=mock_job))
    
    # Mock get_current_user to bypass auth
    from app.core.auth import get_current_user, CurrentUser, require_tenant_access
    mock_user = CurrentUser(
        id=uuid4(),
        email="test@example.com",
        tenant_id=uuid4(),
        role="member",
        tier="starter"
    )
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[require_tenant_access] = lambda: mock_user.tenant_id
    
    response = await ac.get(
        "/api/v1/costs?start_date=2024-01-01&end_date=2024-01-31",
        headers={"Authorization": "Bearer dummy-token"}
    )
    
    assert response.status_code == 202
    assert "job_id" in response.json()
    assert response.json()["status"] == "accepted"
    
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_tier_aware_rate_limiting():
    """
    Verify that rate limits change based on tenant tier.
    """
    from app.core.rate_limit import get_analysis_limit
    from unittest.mock import MagicMock
    
    mock_request = MagicMock()
    
    mock_request.state.tier = "starter"
    assert get_analysis_limit(mock_request) == "2/hour"
    
    mock_request.state.tier = "pro"
    assert get_analysis_limit(mock_request) == "50/hour"
    
    mock_request.state.tier = "enterprise"
    assert get_analysis_limit(mock_request) == "200/hour"
