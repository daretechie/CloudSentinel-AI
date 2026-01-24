"""
Cost Management Job Handlers
"""
import structlog
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.background_job import BackgroundJob
from app.modules.governance.domain.jobs.handlers.base import BaseJobHandler
from app.modules.reporting.domain.service import ReportingService

logger = structlog.get_logger()


class CostIngestionHandler(BaseJobHandler):
    """Processes high-fidelity cost ingestion for cloud accounts (Multi-Cloud)."""
    
    async def execute(self, job: BackgroundJob, db: AsyncSession) -> Dict[str, Any]:
        tenant_id = job.tenant_id
        if not tenant_id:
            raise ValueError("tenant_id required for cost_ingestion")
            
        service = ReportingService(db)
        # Default ingestion range: 7 days (Audit requirement)
        return await service.ingest_costs_for_tenant(tenant_id, days=7)


class CostForecastHandler(BaseJobHandler):
    """Handle multi-tenant cost forecasting as a background job."""
    
    async def execute(self, job: BackgroundJob, db: AsyncSession) -> Dict[str, Any]:
        from app.modules.reporting.domain.aggregator import CostAggregator
        from app.shared.analysis.forecaster import SymbolicForecaster
        from datetime import date
        
        payload = job.payload or {}
        tenant_id = job.tenant_id
        start_date = date.fromisoformat(payload.get("start_date"))
        end_date = date.fromisoformat(payload.get("end_date"))
        days = payload.get("days", 30)
        provider = payload.get("provider")
        
        # 1. Fetch full summary for forecasting
        summary = await CostAggregator.get_summary(
            db, tenant_id, start_date, end_date, provider
        )
        
        if not summary.records:
            return {"status": "skipped", "reason": "no_data"}
            
        # 2. Run deterministic forecast
        result = await SymbolicForecaster.forecast(
            summary.records, 
            days=days,
            db=db,
            tenant_id=tenant_id
        )
        
        return {
            "status": "completed",
            "forecast": result,
            "tenant_id": str(tenant_id)
        }


class CostExportHandler(BaseJobHandler):
    """Handle large cost data exports asynchronously."""
    
    async def execute(self, job: BackgroundJob, db: AsyncSession) -> Dict[str, Any]:
        from app.modules.reporting.domain.aggregator import CostAggregator
        from datetime import date
        
        payload = job.payload or {}
        tenant_id = job.tenant_id
        start_date = date.fromisoformat(payload.get("start_date"))
        end_date = date.fromisoformat(payload.get("end_date"))
        export_format = payload.get("format", "json")
        
        # 1. Get cached breakdown for fast aggregation
        breakdown = await CostAggregator.get_cached_breakdown(
            db, tenant_id, start_date, end_date
        )
        
        # 2. For detailed export, fetch full records
        summary = await CostAggregator.get_summary(
            db, tenant_id, start_date, end_date
        )
        
        return {
            "status": "completed",
            "export_format": export_format,
            "records_exported": len(summary.records) if summary.records else 0,
            "total_cost_usd": float(summary.total_cost) if summary.total_cost else 0,
            "download_url": None  # In production: S3 presigned URL
        }


class CostAggregationHandler(BaseJobHandler):
    """Handle large cost data aggregations asynchronously."""
    
    async def execute(self, job: BackgroundJob, db: AsyncSession) -> Dict[str, Any]:
        from app.modules.reporting.domain.aggregator import CostAggregator
        from datetime import date
        
        payload = job.payload or {}
        tenant_id = job.tenant_id
        start_date = date.fromisoformat(payload.get("start_date"))
        end_date = date.fromisoformat(payload.get("end_date"))
        provider = payload.get("provider")
        
        result = await CostAggregator.get_summary(
            db, tenant_id, start_date, end_date, provider
        )
        
        return {
            "status": "completed",
            "total_cost_usd": float(result.total_cost),
            "record_count": len(result.records),
            "by_service": {k: float(v) for k, v in result.by_service.items()}
        }
