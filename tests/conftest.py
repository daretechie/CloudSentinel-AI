import pytest
import asyncio
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db.session import async_session_maker
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
async def ac() -> AsyncGenerator[AsyncClient, None]:
    """
    Async HTTP client for testing FastAPI endpoints.
    Uses ASGITransport for in-process testing.
    """
    # Mock scheduler in app state to avoid AttributeError in health check
    from unittest.mock import MagicMock
    mock_scheduler = MagicMock()
    mock_scheduler.get_status.return_value = {"status": "running", "jobs": 0}
    app.state.scheduler = mock_scheduler

    async with AsyncClient(
        transport=ASGITransport(app=app), 
        base_url="http://test"
    ) as client:
        yield client

@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """
    Provides a clean database session for each test.
    Rolls back changes after the test completes to maintain isolation.
    """
    async with async_session_maker() as session:
        yield session
        await session.rollback()
