"""
Rate Limiting Middleware for Valdrix

Provides API rate limiting using slowapi (built on limits library).
Configurable via environment variables.
"""

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import FastAPI, Request
from starlette.responses import Response
import structlog

from app.core.config import get_settings

logger = structlog.get_logger()

# Create limiter instance with IP-based identification
limiter = Limiter(key_func=get_remote_address)


def setup_rate_limiting(app: FastAPI) -> None:
    """
    Configure rate limiting for the FastAPI application.
    
    Default limits (configurable via settings):
    - 100 requests/minute for general API
    - 10 requests/minute for analysis endpoints (LLM calls)
    - 30 requests/minute for authentication
    """
    settings = get_settings()
    
    # Add rate limit exceeded handler
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    
    logger.info("rate_limiting_configured", default_limit="100/minute")


# Rate limit decorators for use in routes
def rate_limit(limit: str = "100/minute"):
    """
    Decorator to apply rate limiting to an endpoint.
    
    Usage:
        @router.get("/expensive-operation")
        @rate_limit("10/minute")
        async def expensive_operation():
            ...
    
    Args:
        limit: Rate limit string (e.g., "100/minute", "10/second", "1000/hour")
    """
    return limiter.limit(limit)


# Pre-configured rate limiters for common use cases
standard_limit = limiter.limit("100/minute")
analysis_limit = limiter.limit("10/minute")  # For LLM-based analysis (expensive)
auth_limit = limiter.limit("30/minute")      # For auth endpoints
