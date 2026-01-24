"""
Zombie Resource Scan Job Handlers
"""
import structlog
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.background_job import BackgroundJob
from app.modules.governance.domain.jobs.handlers.base import BaseJobHandler

logger = structlog.get_logger()


class ZombieScanHandler(BaseJobHandler):
    """Handle zombie resource scan job (Multi-Cloud)."""
    
    async def execute(self, job: BackgroundJob, db: AsyncSession) -> Dict[str, Any]:
        from app.modules.optimization.domain.service import ZombieService
        
        tenant_id = job.tenant_id
        if not tenant_id:
            raise ValueError("tenant_id required for zombie_scan")
            
        payload = job.payload or {}
        regions = payload.get("regions", "us-east-1")
        
        async def checkpoint_result(category_key, items):
            """Durable checkpoint: save partial results to DB."""
            if not job.payload:
                job.payload = {}
            if "partial_scan" not in job.payload:
                job.payload["partial_scan"] = {}
            
            job.payload["partial_scan"][category_key] = items

        service = ZombieService(db)
        results = await service.scan_for_tenant(
            tenant_id=tenant_id,
            region=regions,
            analyze=payload.get("analyze", False),
            on_category_complete=checkpoint_result
        )

        return {
            "status": "completed",
            "zombies_found": sum(len(v) for k, v in results.items() if isinstance(v, list)),
            "total_waste": results.get("total_monthly_waste", 0.0),
            "results": results
        }
