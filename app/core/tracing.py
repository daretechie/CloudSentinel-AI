"""
Trace ID Middleware - Observability Enhancement

Adds correlation IDs to all requests and background jobs for distributed tracing.
Makes debugging across job queue, API, and LLM calls much easier.

Usage:
    # In FastAPI app
    app.add_middleware(TraceIdMiddleware)
    
    # In logs
    logger.info("processing", trace_id=get_current_trace_id())
"""

import uuid
from contextvars import ContextVar
from typing import Optional
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import structlog

# Context variable for trace ID (thread-safe)
_trace_id_var: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)

logger = structlog.get_logger()


def get_current_trace_id() -> Optional[str]:
    """Get the current trace ID from context."""
    return _trace_id_var.get()


def set_trace_id(trace_id: str) -> None:
    """Set the trace ID in context."""
    _trace_id_var.set(trace_id)


def generate_trace_id() -> str:
    """Generate a new trace ID."""
    return str(uuid.uuid4())[:8]  # Short ID for readability


class TraceIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds trace IDs to all requests.
    
    - Accepts existing trace ID from X-Trace-Id header
    - Generates new trace ID if none provided
    - Adds trace ID to response headers
    - Sets trace ID in context for logging
    """
    
    async def dispatch(self, request: Request, call_next):
        # Get existing trace ID or generate new one
        trace_id = request.headers.get("X-Trace-Id") or generate_trace_id()
        
        # Set in context for logging
        set_trace_id(trace_id)
        
        # Add to request state for access in routes
        request.state.trace_id = trace_id
        
        # Log request with trace ID
        logger.info(
            "request_start",
            trace_id=trace_id,
            method=request.method,
            path=request.url.path
        )
        
        try:
            response = await call_next(request)
            
            # Add trace ID to response headers
            response.headers["X-Trace-Id"] = trace_id
            
            logger.info(
                "request_end",
                trace_id=trace_id,
                status_code=response.status_code
            )
            
            return response
            
        except Exception as e:
            logger.error(
                "request_error",
                trace_id=trace_id,
                error=str(e)
            )
            raise


def add_trace_to_job_payload(payload: dict, trace_id: Optional[str] = None) -> dict:
    """
    Add trace ID to job payload for cross-job tracing.
    
    Usage in job creation:
        payload = add_trace_to_job_payload({"task": "analyze"})
        await enqueue_job(db, JobType.FINOPS_ANALYSIS, payload=payload)
    """
    payload = payload.copy()
    payload["_trace_id"] = trace_id or get_current_trace_id() or generate_trace_id()
    return payload


def get_trace_from_job(job) -> Optional[str]:
    """Extract trace ID from job payload."""
    if job.payload:
        return job.payload.get("_trace_id")
    return None


# Structlog processor to add trace ID automatically
def add_trace_id_processor(logger, method_name, event_dict):
    """
    Structlog processor that adds trace ID to all log entries.
    
    Add to structlog config:
        structlog.configure(
            processors=[add_trace_id_processor, ...]
        )
    """
    trace_id = get_current_trace_id()
    if trace_id and "trace_id" not in event_dict:
        event_dict["trace_id"] = trace_id
    return event_dict
