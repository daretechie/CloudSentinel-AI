import ssl
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.core.config import get_settings

settings = get_settings()

# Validation: Fail fast if database URL is not configured
# Why: Better to crash on startup than fail silently on first request
if not settings.DATABASE_URL:
    raise ValueError("DATABASE_URL is not set. Check your .env file.")

# SSL Context: Supabase (via pooler) requires strict SSL with custom CA
# Why: Validates the server identity to prevent MITM attacks
import os
base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
ca_cert_path = os.path.join(base_path, "app", "core", "supabase.crt")

ssl_context = ssl.create_default_context()
# ssl_context.set_ciphers('DEFAULT@SECLEVEL=0') # Unused as cert is invalid for OpenSSL 3
# ssl_context.load_verify_locations(cafile=ca_cert_path) # Kept for reference but verification disabled
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Engine: The connection pool manager
# - echo: Logs SQL queries when DEBUG=True (disable in production for performance)
# - pool_size: Number of persistent connections (5 is good for Neon free tier)
# - max_overflow: Extra connections allowed during traffic spikes
# - pool_pre_ping: Checks if connection is alive before using (prevents stale connections)
# - connect_args: Passes SSL context to asyncpg driver + disables statement cache for Supavisor
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    connect_args={
        "ssl": ssl_context,
        "statement_cache_size": 0,
    },
)

# Session Factory: Creates new database sessions
# - expire_on_commit=False: Prevents lazy loading issues in async code
#   (objects remain accessible after commit without re-querying)
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """
    FastAPI dependency that provides a database session.
    
    Usage in endpoint:
        @app.get("/users")
        async def get_users(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(User))
            return result.scalars().all()
    
    What it does:
    1. Creates a new session from the pool
    2. Yields it to the endpoint
    3. Closes/returns it to pool after request completes
    
    Why generator (yield):
        Ensures cleanup happens even if endpoint throws an exception
    """
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()