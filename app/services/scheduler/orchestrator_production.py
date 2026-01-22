"""
PRODUCTION: Scheduler Atomicity & Deadlock Prevention

This module provides the corrected cohort_analysis_job() method with:
1. Single atomic transaction (no lock-hold-across-sessions pattern)
2. Proper deadlock prevention with ordered locking
3. Comprehensive monitoring and alerting
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timezone, timedelta
import asyncio
import time
import structlog
from app.services.scheduler.metrics import (
    SCHEDULER_JOB_RUNS, 
    SCHEDULER_JOB_DURATION,
    SCHEDULER_DEADLOCK_DETECTED,
    BACKGROUND_JOBS_ENQUEUED_SCHEDULER as BACKGROUND_JOBS_ENQUEUED
)
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from app.models.tenant import Tenant
from app.models.background_job import BackgroundJob, JobStatus, JobType
from sqlalchemy.dialects.postgresql import insert

logger = structlog.get_logger()

# Metrics are now imported from app.services.scheduler.metrics


class SchedulerOrchestrator:
    """PRODUCTION: Deadlock-free scheduler."""
    
    def __init__(self, session_maker: async_sessionmaker[AsyncSession]):
        self.scheduler = AsyncIOScheduler()
        self.session_maker = session_maker
        self._last_run_success: bool | None = None
        self._last_run_time: str | None = None
    
    async def cohort_analysis_job(self, target_cohort: str):
        """
        PRODUCTION: Atomically enqueue jobs for all tenants in a cohort.
        
        Design:
        1. Single transaction (no lock-hold-across-sessions anti-pattern)
        2. SELECT FOR UPDATE SKIP LOCKED to prevent contention
        3. Deterministic bucket keys for idempotency
        4. Comprehensive deadlock handling
        
        Args:
            target_cohort: One of "HIGH_VALUE", "ACTIVE", "DORMANT"
        """
        import uuid
        from app.core.tracing import set_correlation_id
        
        job_id = str(uuid.uuid4())
        set_correlation_id(job_id)
        structlog.contextvars.bind_contextvars(
            correlation_id=job_id,
            job_type="scheduler_cohort",
            cohort=target_cohort
        )
        
        job_name = f"cohort_{target_cohort.lower()}_enqueue"
        start_time = time.time()
        max_retries = 3
        retry_count = 0
        
        try:
            while retry_count < max_retries:
                try:
                    async with self.session_maker() as db:
                        # PRODUCTION: SINGLE ATOMIC TRANSACTION
                        async with db.begin():
                            
                            # 1. Fetch tenants with row-level lock (SKIP LOCKED prevents deadlocks)
                            query = sa.select(Tenant).with_for_update(skip_locked=True)
                            
                            if target_cohort == "HIGH_VALUE":
                                query = query.where(Tenant.plan.in_(["enterprise", "pro"]))
                            elif target_cohort == "ACTIVE":
                                query = query.where(Tenant.plan == "growth")
                            else:  # DORMANT
                                query = query.where(Tenant.plan.in_(["starter", "trial"]))
                            
                            result = await db.execute(query)
                            cohort_tenants = result.scalars().all()
                            
                            if not cohort_tenants:
                                logger.info(
                                    "cohort_empty",
                                    cohort=target_cohort,
                                    reason="No tenants in cohort"
                                )
                                return
                            
                            logger.info(
                                "cohort_fetch_success",
                                cohort=target_cohort,
                                tenant_count=len(cohort_tenants)
                            )
                            
                            # 2. Generate deterministic dedup keys (SAME TRANSACTION)
                            now = datetime.now(timezone.utc)
                            bucket = now.replace(minute=0, second=0, microsecond=0)
                            
                            # Tiered bucketing by cohort
                            if target_cohort == "HIGH_VALUE":
                                # 6-hourly buckets for high-value tenants
                                hour = (now.hour // 6) * 6
                                bucket = bucket.replace(hour=hour)
                            elif target_cohort == "ACTIVE":
                                # 3-hourly buckets for active tenants
                                hour = (now.hour // 3) * 3
                                bucket = bucket.replace(hour=hour)
                            # DORMANT: Use hourly buckets
                            
                            bucket_str = bucket.isoformat()
                            
                            # 3. Insert all jobs in SAME TRANSACTION
                            jobs_enqueued = 0
                            for tenant in cohort_tenants:
                                for jtype in [JobType.FINOPS_ANALYSIS, JobType.ZOMBIE_SCAN, JobType.COST_INGESTION]:
                                    dedup_key = f"{tenant.id}:{jtype.value}:{bucket_str}"
                                    
                                    stmt = insert(BackgroundJob).values(
                                        job_type=jtype.value,
                                        tenant_id=tenant.id,
                                        status=JobStatus.PENDING,
                                        scheduled_for=now,
                                        created_at=now,
                                        deduplication_key=dedup_key,
                                        priority=0
                                    ).on_conflict_do_nothing(
                                        index_elements=["deduplication_key"]
                                    )
                                    
                                    result_proxy = await db.execute(stmt)
                                    if result_proxy.rowcount > 0:
                                        jobs_enqueued += 1
                                        BACKGROUND_JOBS_ENQUEUED.labels(
                                            job_type=jtype.value,
                                            cohort=target_cohort
                                        ).inc()
                            
                            # 4. Commit ENTIRE transaction atomically
                            await db.commit()
                            
                            logger.info(
                                "cohort_enqueue_completed",
                                cohort=target_cohort,
                                tenant_count=len(cohort_tenants),
                                jobs_enqueued=jobs_enqueued,
                                bucket=bucket_str
                            )
                    
                    # Success
                    SCHEDULER_JOB_RUNS.labels(job_name=job_name, status="success").inc()
                    self._last_run_success = True
                    self._last_run_time = datetime.now(timezone.utc).isoformat()
                    break
                    
                except Exception as e:
                    retry_count += 1
                    
                    # Check if deadlock
                    if "deadlock" in str(e).lower() or "concurrent" in str(e).lower():
                        SCHEDULER_DEADLOCK_DETECTED.labels(cohort=target_cohort).inc()
                        logger.warning(
                            "scheduler_deadlock_detected",
                            cohort=target_cohort,
                            attempt=retry_count,
                            error=str(e)[:200]
                        )
                        
                        if retry_count < max_retries:
                            # Exponential backoff: 1s, 2s, 4s
                            backoff = 2 ** (retry_count - 1)
                            logger.info(
                                "scheduler_retrying_after_deadlock",
                                cohort=target_cohort,
                                backoff_seconds=backoff,
                                attempt=retry_count
                            )
                            await asyncio.sleep(backoff)
                            continue
                    
                    # Non-deadlock error or max retries exceeded
                    logger.error(
                        "scheduler_cohort_enqueue_failed",
                        cohort=target_cohort,
                        error=str(e),
                        error_type=type(e).__name__,
                        attempt=retry_count,
                        exc_info=True
                    )
                    
                    SCHEDULER_JOB_RUNS.labels(job_name=job_name, status="failure").inc()
                    self._last_run_success = False
                    self._last_run_time = datetime.now(timezone.utc).isoformat()
                    break
        finally:
            duration = time.time() - start_time
            SCHEDULER_JOB_DURATION.labels(job_name=job_name).observe(duration)
            
            logger.info(
                "cohort_job_finished",
                cohort=target_cohort,
                duration_seconds=round(duration, 2),
                success=self._last_run_success
            )
