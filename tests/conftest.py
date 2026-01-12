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
@pytest.fixture(scope="session", autouse=True)
def mock_settings():
    """
    Globally override settings for all tests to ensure isolation from .env
    and valid encryption keys.
    """
    from app.core.config import get_settings, Settings
    from cryptography.fernet import Fernet
    from app.main import app
    
    # Generate a valid key for testing
    test_key = Fernet.generate_key().decode()
    
    # Create mock settings
    start_settings = Settings(
        DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
        SUPABASE_JWT_SECRET="test-secret",
        ENCRYPTION_KEY=test_key,
        # Add other critical defaults here
    )
    
    # Override the dependency
    app.dependency_overrides[get_settings] = lambda: start_settings
    
    # Also patch the global settings object in security.py if it's imported at module Level
    # Ideally, code should use dependencies, but for models relying on global import:
    with  pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.core.security.settings", start_settings)
        yield start_settings
    
    app.dependency_overrides.clear()
