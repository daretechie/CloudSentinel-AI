from datetime import date
from typing import Annotated, Any
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
import structlog
from pydantic import BaseModel

from app.core.auth import CurrentUser, requires_role
from app.db.session import get_db
from app.services.llm.analyzer import FinOpsAnalyzer
from app.models.llm import LLMUsage
from app.core.dependencies import get_analyzer, requires_feature
from app.services.costs.aggregator import CostAggregator
from app.core.rate_limit import rate_limit, ANALYSIS_LIMIT

class CostResponse(BaseModel):
    analysis: Any

router = APIRouter(tags=["Costs & Analysis"])
logger = structlog.get_logger()


@router.get("")
async def get_costs(
    start_date: date,
    end_date: date,
    user: Annotated[CurrentUser, Depends(requires_role("member"))],
    provider: str | None = Query(None, description="Filter by cloud provider (aws, azure, gcp)"),
    db: AsyncSession = Depends(get_db),
):
    """Retrieves aggregated cloud costs and carbon for a date range."""
    return await CostAggregator.get_basic_breakdown(
        db, user.tenant_id, start_date, end_date, provider
    )


@router.get("/analyze", response_model=CostResponse)
@rate_limit(ANALYSIS_LIMIT)
async def analyze_costs(
    start_date: date,
    end_date: date,
    analyzer: Annotated[FinOpsAnalyzer, Depends(get_analyzer)],
    user: Annotated[CurrentUser, Depends(requires_feature("llm_analysis"))],
    db: AsyncSession = Depends(get_db),
):
    """AI-powered analysis of cloud costs. Requires Growth tier or higher."""
    # Use aggregator to fetch summary
    summary = await CostAggregator.get_summary(
        db, user.tenant_id, start_date, end_date
    )
    
    if not summary.records:
        return {"analysis": "No cost data available for analysis period."}

    logger.info("starting_sentinel_analysis_db", 
                tenant_id=str(user.tenant_id),
                start=start_date, 
                end=end_date)

    insights = await analyzer.analyze(
        summary,
        tenant_id=user.tenant_id,
        db=db,
    )

    return {"analysis": insights}


@router.get("/llm/usage")
async def get_llm_usage(
    user: Annotated[CurrentUser, Depends(requires_role("member"))],
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, le=200),
):
    """Get LLM usage history for the tenant."""
    from sqlalchemy import select
    result = await db.execute(
        select(LLMUsage)
        .where(LLMUsage.tenant_id == user.tenant_id)
        .order_by(LLMUsage.created_at.desc())
        .limit(limit)
    )
    records = result.scalars().all()

    return {
        "usage": [
            {
                "id": str(r.id),
                "model": r.model,
                "provider": r.provider,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "total_tokens": r.total_tokens,
                "cost_usd": float(r.cost_usd) if r.cost_usd else 0,
                "request_type": r.request_type,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ],
        "count": len(records),
    }
