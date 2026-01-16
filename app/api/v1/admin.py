from fastapi import APIRouter, Header, HTTPException, Request
from app.core.config import get_settings
import secrets
import structlog

router = APIRouter(tags=["Admin Utilities"])
logger = structlog.get_logger()

@router.post("/trigger-analysis")
async def trigger_analysis(request: Request, x_admin_key: str = Header(..., alias="X-Admin-Key")):
    """Manually trigger a scheduled analysis job."""
    settings = get_settings()

    if not settings.ADMIN_API_KEY:
        logger.error("admin_key_not_configured")
        raise HTTPException(
            status_code=503,
            detail="Admin endpoint not configured. Set ADMIN_API_KEY."
        )

    if not secrets.compare_digest(x_admin_key, settings.ADMIN_API_KEY):
        logger.warning("admin_auth_failed")
        raise HTTPException(status_code=403, detail="Forbidden")

    logger.info("manual_trigger_requested")
    # Access scheduler from app state (passed via request.app)
    await request.app.state.scheduler.daily_analysis_job()
    return {"status": "triggered", "message": "Daily analysis job executed."}
