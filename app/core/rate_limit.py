"""
Rate Limiting Middleware for Valdrix

Provides API rate limiting using slowapi (built on limits library).
Configurable via environment variables.
"""

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import FastAPI, Request
import structlog

from app.core.config import get_settings

logger = structlog.get_logger()

def context_aware_key(request: Request) -> str:
    """
    Identifies the requester for rate limiting.
    1. Uses tenant_id if user is authenticated (B2B fairness).
    2. Falls back to sub from JWT if auth hasn't run but token exists (Prevents NAT issues).
    3. Falls back to remote IP (Defense-in-depth).
    """
    # Try request state (already populated by get_current_user dependency)
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        return f"tenant:{tenant_id}"
    
    # Fast check for Authorization header (no DB lookup)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        try:
            # SEC-02: Hash token for rate limiting instead of decoding
            # This prevents bypass via forged JWTs with same 'sub' claim
            import hashlib
            token_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
            return f"token:{token_hash}"
        except Exception:
            pass

    return get_remote_address(request)

def get_limiter() -> Limiter:
    """Lazy initialization of the Limiter instance."""
    global _limiter
    if _limiter is None:
        settings = get_settings()
        storage_uri = settings.REDIS_URL or "memory://"
        _limiter = Limiter(
            key_func=context_aware_key,
            storage_uri=storage_uri,
            strategy="fixed-window"
        )
    return _limiter

_limiter = None

def setup_rate_limiting(app: FastAPI) -> None:
    """
    Configure rate limiting for the FastAPI application.
    """
    l = get_limiter()
    # Add rate limit exceeded handler
    app.state.limiter = l
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    logger.info("rate_limiting_configured")

# Rate limit decorators for use in routes
def rate_limit(limit: str = "100/minute"):
    """Decorator to apply rate limiting to an endpoint."""
    return get_limiter().limit(limit)

# Pre-configured rate limits (now using strings for delay)
# Route handlers can use @rate_limit("100/minute") or these helpers
STANDARD_LIMIT = "100/minute"
ANALYSIS_LIMIT = "10/minute"
AUTH_LIMIT = "30/minute"
