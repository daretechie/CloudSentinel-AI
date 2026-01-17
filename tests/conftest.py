import pytest
import asyncio
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db.session import async_session_maker
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.fixture(autouse=True)
async def cleanup_engine():
    """Ensure the database engine is disposed after EVERY test to prevent leaks."""
    yield
    from app.db.session import engine
    await engine.dispose()

@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """
    Provides a clean database session for each test using a connection-bound 
    transaction. This is more robust for asyncpg than session-level begin().
    """
    from app.db.session import engine
    connection = await engine.connect()
    # Start the outermost transaction
    trans = await connection.begin()
    
    # Create session bound to this connection
    session = AsyncSession(bind=connection, join_transaction=True, expire_on_commit=False)
    
    try:
        yield session
    finally:
        await session.close()
        # Rollback everything to leave DB clean
        await trans.rollback()
        await connection.close()

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
        TESTING=True,
        SUPABASE_JWT_SECRET="test-secret",
        ENCRYPTION_KEY=test_key,
        DB_POOL_SIZE=5,
        DB_MAX_OVERFLOW=0
    )
    
    # Override the dependency
    app.dependency_overrides[get_settings] = lambda: start_settings
    
    # Patch settings globally
    with  pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.core.security.settings", start_settings)
        mp.setattr("app.db.session.settings", start_settings)
        yield start_settings
    
    # Cleanup
    app.dependency_overrides.clear()
@pytest.fixture
async def ac() -> AsyncGenerator[AsyncClient, None]:
    """
    Async client fixture for testing API endpoints.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
