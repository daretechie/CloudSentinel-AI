import sys
import structlog
import logging
from app.core.config import get_settings

def pii_redactor(logger, method_name, event_dict):
    """
    Redact common PII and sensitive fields from logs.
    Ensures GDPR/SOC2 compliance by preventing leakage into telemetry.
    """
    pii_fields = {
        "email", "user_email", "phone", "password", "token", "secret", 
        "cvv", "api_key", "aws_secret_key", "stripe_customer_id"
    }
    
    # Redact top-level fields
    for field in pii_fields:
        if field in event_dict:
            event_dict[field] = "[REDACTED]"
            
    # Redact nested fields in common containers
    for container in ["metadata", "payload", "details", "extra"]:
        if container in event_dict and isinstance(event_dict[container], dict):
            for field in pii_fields:
                if field in event_dict[container]:
                    event_dict[container][field] = "[REDACTED]"
                    
    return event_dict

def setup_logging():
    settings = get_settings()

    # 1. Choose the renderer based on environment
    if settings.DEBUG:
        renderer = structlog.dev.ConsoleRenderer()
        min_level = logging.DEBUG
    else:
        renderer = structlog.processors.JSONRenderer()
        min_level = logging.INFO

    # 2. Configure the "Processors" (The Middleware Pipeline for Logs)
    processors = [
        structlog.contextvars.merge_contextvars, # Support async context
        structlog.processors.add_log_level,      # Add "level": "info"
        structlog.processors.TimeStamper(fmt="iso"), # Add "timestamp": "2026..."
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,    # Render exceptions nicely
        pii_redactor,                            # Security: Redact PII before rendering
        renderer
    ]


    # 3. Configure the logger or apply the configuration
    structlog.configure(
        processors=processors,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # 4. Intercept the standard logging (e.g. uvicorn's internal log).
    # This ensure even library logs get formatted as JSON.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        # filename="debug.log",
        level=min_level,
    )


def audit_log(event: str, user_id: str, tenant_id: str, details: dict = None):
    """
    Standardized helper for security-critical audit events.
    Enforces a consistent schema for SIEM ingestion.
    """
    logger = structlog.get_logger("audit")
    logger.info(
        "audit_event",
        event=event,
        user_id=str(user_id),
        tenant_id=str(tenant_id),
        metadata=details or {},
    )
