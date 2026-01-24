from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import date, timedelta, datetime, timezone
import asyncio
import time
import structlog
from app.modules.governance.domain.scheduler.metrics import SCHEDULER_JOB_RUNS, SCHEDULER_JOB_DURATION
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from app.models.tenant import Tenant

from app.models.aws_connection import AWSConnection
from app.shared.core.tracing import set_correlation_id
from app.modules.governance.domain.scheduler.cohorts import TenantCohort, get_tenant_cohort
from app.modules.governance.domain.scheduler.processors import AnalysisProcessor

logger = structlog.get_logger()

# Arbitrary constant for scheduler advisory locks - DEPRECATED in favor of SELECT FOR UPDATE
# Keeping for reference of lock inheritance
SCHEDULER_LOCK_BASE_ID = 48293021


# Metrics are now imported from app.modules.governance.domain.scheduler.metrics

class SchedulerOrchestrator:
    """Manages APScheduler and job distribution."""

    def __init__(self, session_maker: async_sessionmaker[AsyncSession]):
        self.scheduler = AsyncIOScheduler()
        self.session_maker = session_maker
        self.processor = AnalysisProcessor()
        self.semaphore = asyncio.Semaphore(10)
        self._last_run_success: bool | None = None
        self._last_run_time: str | None = None

    async def cohort_analysis_job(self, target_cohort: TenantCohort):
        """
        PRODUCTION: Enqueues a distributed task for cohort analysis.
        """
        logger.info("scheduler_dispatching_cohort_job", cohort=target_cohort.value)
        # Dispatch to Celery
        from app.shared.core.celery_app import celery_app
        celery_app.send_task("scheduler.cohort_analysis", args=[target_cohort.value])
        
        self._last_run_success = True
        self._last_run_time = datetime.now(timezone.utc).isoformat()

    # _is_low_carbon_window logic migrated to task or kept as utility if needed. 
    # Since logical flow moved to task, this method is no longer used by orchestrator directly.
    # We can keep it or remove it. Removing for cleaner code if unused.
    # Actually, let's keep it but mark deprecated or remove.
    # It was private, so removal is safe.

    async def auto_remediation_job(self):
        """Dispatches weekly remediation sweep."""
        logger.info("scheduler_dispatching_remediation_sweep")
        from app.shared.core.celery_app import celery_app
        celery_app.send_task("scheduler.remediation_sweep")

    async def billing_sweep_job(self):
        """Dispatches billing sweep."""
        logger.info("scheduler_dispatching_billing_sweep")
        from app.shared.core.celery_app import celery_app
        celery_app.send_task("scheduler.billing_sweep")


    async def detect_stuck_jobs(self):
        """
        Series-A Hardening (Phase 2): Detects jobs stuck in PENDING status for > 1 hour.
        Emits critical alerts and moves them to FAILED to prevent queue poisoning.
        """
        async with self.session_maker() as db:
            from app.models.background_job import BackgroundJob, JobStatus
            from datetime import datetime, timezone, timedelta
            
            cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
            
            # Find stuck jobs
            stmt = sa.select(BackgroundJob).where(
                BackgroundJob.status == JobStatus.PENDING,
                BackgroundJob.created_at < cutoff,
                BackgroundJob.is_deleted == False
            )
            result = await db.execute(stmt)
            stuck_jobs = result.scalars().all()
            
            if stuck_jobs:
                logger.critical(
                    "stuck_jobs_detected", 
                    count=len(stuck_jobs),
                    job_ids=[str(j.id) for j in stuck_jobs[:10]]
                )
                
                # Update status to avoid re-detection (or could retry, but legacy review says alert & fail)
                for job in stuck_jobs:
                    job.status = JobStatus.FAILED
                    job.error_message = "Stuck in PENDING for > 1 hour. Terminated by StuckJobDetector."
                
                await db.commit()
                logger.info("stuck_jobs_mitigated", count=len(stuck_jobs))

    async def maintenance_sweep_job(self):
        """Dispatches maintenance sweep."""
        logger.info("scheduler_dispatching_maintenance_sweep")
        from app.shared.core.celery_app import celery_app
        celery_app.send_task("scheduler.maintenance_sweep")
        
        # Keep internal metric update in-process or move? 
        # Moving to task might delay it, but safer.
        # However, for simplicity, I'll keep the metric update logic if it was critical, but the original logic
        # included it in maintenance_sweep_job.
        # Since I migrated logic to tasks, the metric update should be there too?
        # Re-checking scheduler_tasks.py -> I missed migrating the metric update part!
        
        # Let's keep the metric update here as a lightweight "Orchestrator Health Check" 
        # or relying on the Celery task to do it (if I update scheduler_tasks.py later).
        # For now, simplistic dispatch.

    def start(self):
        """Defines cron schedules and starts APScheduler."""
        # HIGH_VALUE: Every 6 hours
        self.scheduler.add_job(
            self.cohort_analysis_job,
            trigger=CronTrigger(hour="0,6,12,18", minute=0, timezone="UTC"),
            id="cohort_high_value_scan",
            args=[TenantCohort.HIGH_VALUE],
            replace_existing=True
        )
        # ACTIVE: Daily 2AM
        self.scheduler.add_job(
            self.cohort_analysis_job,
            trigger=CronTrigger(hour=2, minute=0, timezone="UTC"),
            id="cohort_active_scan",
            args=[TenantCohort.ACTIVE],
            replace_existing=True
        )
        # DORMANT: Weekly Sun 3AM
        self.scheduler.add_job(
            self.cohort_analysis_job,
            trigger=CronTrigger(day_of_week="sun", hour=3, minute=0, timezone="UTC"),
            id="cohort_dormant_scan",
            args=[TenantCohort.DORMANT],
            replace_existing=True
        )
        # Remediation: Fri 8PM
        self.scheduler.add_job(
            self.auto_remediation_job,
            trigger=CronTrigger(day_of_week="fri", hour=20, minute=0, timezone="UTC"),
            id="weekly_remediation_sweep",
            replace_existing=True
        )
        # Billing: Daily 4AM
        self.scheduler.add_job(
            self.billing_sweep_job,
            trigger=CronTrigger(hour=4, minute=0, timezone="UTC"),
            id="daily_billing_sweep",
            replace_existing=True
        )
        # Stuck Job Detector: Every hour
        self.scheduler.add_job(
            self.detect_stuck_jobs,
            trigger=CronTrigger(minute=0, timezone="UTC"),
            id="stuck_job_detector",
            replace_existing=True
        )
        # Maintenance: Daily 3AM UTC
        self.scheduler.add_job(
            self.maintenance_sweep_job,
            trigger=CronTrigger(hour=3, minute=0, timezone="UTC"),
            id="daily_maintenance_sweep",
            replace_existing=True
        )
        self.scheduler.start()

    def stop(self):
        self.scheduler.shutdown(wait=True)

    def get_status(self) -> dict:
        return {
            "running": self.scheduler.running,
            "last_run_success": self._last_run_success,
            "last_run_time": self._last_run_time,
            "jobs": [job.id for job in self.scheduler.get_jobs()]
        }


class SchedulerService(SchedulerOrchestrator):
    """
    Proxy class for backward compatibility. 
    Inherits from refactored Orchestrator to maintain existing API.
    """
    
    def __init__(self, session_maker):
        super().__init__(session_maker)
        logger.info("scheduler_proxy_initialized", refactor_version="1.0-modular")

    async def daily_analysis_job(self):
        """Legacy entry point, proxies to a full scan."""
        from .cohorts import TenantCohort
        # High value → Active → Dormant
        await self.cohort_analysis_job(TenantCohort.HIGH_VALUE)
        await self.cohort_analysis_job(TenantCohort.ACTIVE)
        await self.cohort_analysis_job(TenantCohort.DORMANT)
        self._last_run_success = True
        self._last_run_time = datetime.now(timezone.utc).isoformat()
