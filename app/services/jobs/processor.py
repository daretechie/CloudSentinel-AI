"""
Job Processor Service - Phase 7: Scheduler SPOF Resolution

Processes background jobs from the database queue.
Works with pg_cron to provide durable, distributed job processing.

Key Features:
- Survives app restarts (jobs in database)
- Automatic retries with exponential backoff
- Per-tenant job isolation
- Full audit trail

Usage:
    processor = JobProcessor(db)
    await processor.process_pending_jobs()
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Callable, Awaitable
from uuid import UUID
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.background_job import BackgroundJob, JobStatus, JobType

logger = structlog.get_logger()

# Job processing configuration
MAX_JOBS_PER_BATCH = 10
JOB_LOCK_TIMEOUT_MINUTES = 30
BACKOFF_BASE_SECONDS = 60


# Type for job handlers
JobHandler = Callable[[BackgroundJob, AsyncSession], Awaitable[Dict[str, Any]]]


class JobProcessor:
    """
    Processes background jobs from the database queue.
    
    Designed to be called by:
    1. pg_cron (every minute in Supabase)
    2. API endpoint for on-demand processing
    3. Startup hook for catching up
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self._handlers: Dict[str, JobHandler] = {}
        self._register_default_handlers()
    
    def _register_default_handlers(self) -> None:
        """Register default job type handlers."""
        self._handlers[JobType.FINOPS_ANALYSIS] = self._handle_finops_analysis
        self._handlers[JobType.ZOMBIE_SCAN] = self._handle_zombie_scan
        self._handlers[JobType.WEBHOOK_RETRY] = self._handle_webhook_retry
        self._handlers[JobType.NOTIFICATION] = self._handle_notification
    
    def register_handler(self, job_type: str, handler: JobHandler) -> None:
        """Register a custom job handler."""
        self._handlers[job_type] = handler
    
    async def process_pending_jobs(self, limit: int = MAX_JOBS_PER_BATCH) -> Dict[str, Any]:
        """
        Process pending jobs up to the limit.
        
        Called by pg_cron every minute or on-demand.
        Uses SELECT FOR UPDATE SKIP LOCKED for safe concurrency.
        """
        results = {
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "errors": []
        }
        
        try:
            # Fetch pending jobs that are due
            pending_jobs = await self._fetch_pending_jobs(limit)
            
            logger.info(
                "job_processor_batch_start",
                pending_count=len(pending_jobs)
            )
            
            for job in pending_jobs:
                try:
                    await self._process_single_job(job)
                    results["succeeded"] += 1
                except Exception as e:
                    results["failed"] += 1
                    results["errors"].append({
                        "job_id": str(job.id),
                        "error": str(e)
                    })
                results["processed"] += 1
            
            logger.info(
                "job_processor_batch_complete",
                **results
            )
            
        except Exception as e:
            logger.error("job_processor_batch_error", error=str(e))
            results["errors"].append({"batch_error": str(e)})
        
        return results
    
    async def _fetch_pending_jobs(self, limit: int) -> list[BackgroundJob]:
        """Fetch pending jobs that are ready to run."""
        now = datetime.now(timezone.utc)
        
        result = await self.db.execute(
            select(BackgroundJob)
            .where(
                BackgroundJob.status == JobStatus.PENDING,
                BackgroundJob.scheduled_for <= now,
                BackgroundJob.attempts < BackgroundJob.max_attempts
            )
            .order_by(BackgroundJob.scheduled_for)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        
        return list(result.scalars().all())
    
    async def _process_single_job(self, job: BackgroundJob) -> None:
        """Process a single job with error handling."""
        logger.info(
            "job_processing_start",
            job_id=str(job.id),
            job_type=job.job_type,
            attempt=job.attempts + 1
        )
        
        # Mark as running
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        job.attempts += 1
        await self.db.commit()
        
        try:
            # Get handler for job type
            handler = self._handlers.get(job.job_type)
            if not handler:
                raise ValueError(f"No handler for job type: {job.job_type}")
            
            # Execute handler
            result = await handler(job, self.db)
            
            # Mark as completed
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            job.result = result
            job.error_message = None
            
            logger.info(
                "job_processing_success",
                job_id=str(job.id),
                job_type=job.job_type
            )
            
        except Exception as e:
            logger.error(
                "job_processing_failed",
                job_id=str(job.id),
                job_type=job.job_type,
                error=str(e)
            )
            
            job.error_message = str(e)
            
            if job.attempts >= job.max_attempts:
                # Move to dead letter
                job.status = JobStatus.DEAD_LETTER
                job.completed_at = datetime.now(timezone.utc)
            else:
                # Schedule retry with exponential backoff
                backoff_seconds = BACKOFF_BASE_SECONDS * (2 ** (job.attempts - 1))
                job.status = JobStatus.PENDING
                job.scheduled_for = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
        
        await self.db.commit()
    
    # ==================== Job Handlers ====================
    
    async def _handle_finops_analysis(
        self, 
        job: BackgroundJob, 
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Handle FinOps analysis job."""
        from app.services.llm.analyzer import FinOpsAnalyzer
        from app.services.adapters.aws_multitenant import MultiTenantAWSAdapter
        from app.models.aws_connection import AWSConnection
        
        tenant_id = job.tenant_id
        if not tenant_id:
            raise ValueError("tenant_id required for finops_analysis")
        
        # Get AWS connection
        result = await db.execute(
            select(AWSConnection).where(AWSConnection.tenant_id == tenant_id)
        )
        connection = result.scalar_one_or_none()
        
        if not connection:
            return {"status": "skipped", "reason": "no_aws_connection"}
        
        # Fetch costs
        adapter = MultiTenantAWSAdapter(connection)
        from datetime import date, timedelta
        end_date = date.today()
        start_date = end_date - timedelta(days=30)
        
        cost_data = await adapter.get_daily_costs(start_date, end_date)
        
        # Run analysis
        analyzer = FinOpsAnalyzer()
        analysis = await analyzer.analyze(cost_data, tenant_id=tenant_id, db=db)
        
        return {"status": "completed", "analysis_length": len(analysis)}
    
    async def _handle_zombie_scan(
        self, 
        job: BackgroundJob, 
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Handle zombie resource scan job."""
        from app.services.zombies.detector import ZombieDetector
        
        payload = job.payload or {}
        regions = payload.get("regions", ["us-east-1"])
        
        detector = ZombieDetector(region=regions[0])
        results = await detector.scan_all_regions(regions)
        
        return {
            "status": "completed",
            "zombies_found": sum(len(r.get("items", [])) for r in results.get("regions", [])),
            "total_waste": results.get("total_monthly_waste", 0)
        }
    
    async def _handle_webhook_retry(
        self, 
        job: BackgroundJob, 
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Handle webhook retry job (e.g., Paystack)."""
        payload = job.payload or {}
        provider = payload.get("provider", "generic")
        
        if provider == "paystack":
            # Use Paystack-specific handler
            from app.services.billing.webhook_retry import process_paystack_webhook
            return await process_paystack_webhook(job, db)
        
        # Generic HTTP webhook retry
        import httpx
        
        url = payload.get("url")
        data = payload.get("data")
        headers = payload.get("headers", {})
        
        if not url:
            raise ValueError("url required for generic webhook_retry")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=data, headers=headers, timeout=30)
            response.raise_for_status()
        
        return {"status": "completed", "status_code": response.status_code}
    
    async def _handle_notification(
        self, 
        job: BackgroundJob, 
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Handle notification job (Slack, Email, etc.)."""
        from app.services.notifications import NotificationService
        
        payload = job.payload or {}
        channel = payload.get("channel", "slack")
        message = payload.get("message")
        
        if not message:
            raise ValueError("message required for notification")
        
        service = NotificationService(db)
        await service.send(channel=channel, message=message, tenant_id=job.tenant_id)
        
        return {"status": "completed", "channel": channel}


# ==================== Job Creation Helpers ====================

async def enqueue_job(
    db: AsyncSession,
    job_type: str,
    tenant_id: Optional[UUID] = None,
    payload: Optional[Dict[str, Any]] = None,
    scheduled_for: Optional[datetime] = None,
    max_attempts: int = 3
) -> BackgroundJob:
    """
    Enqueue a new background job.
    
    Usage:
        job = await enqueue_job(
            db,
            job_type=JobType.FINOPS_ANALYSIS,
            tenant_id=tenant.id,
            payload={"force_refresh": True}
        )
    """
    job = BackgroundJob(
        job_type=job_type,
        tenant_id=tenant_id,
        payload=payload,
        scheduled_for=scheduled_for or datetime.now(timezone.utc),
        max_attempts=max_attempts,
        created_at=datetime.now(timezone.utc)
    )
    
    db.add(job)
    await db.commit()
    await db.refresh(job)
    
    logger.info(
        "job_enqueued",
        job_id=str(job.id),
        job_type=job_type,
        tenant_id=str(tenant_id) if tenant_id else None
    )
    
    return job
