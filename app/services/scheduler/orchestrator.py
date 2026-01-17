from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import date, timedelta, datetime, timezone
import asyncio
import time
import structlog
from prometheus_client import Counter, Histogram
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from app.models.tenant import Tenant

from app.models.aws_connection import AWSConnection
from app.core.tracing import set_correlation_id
from app.services.scheduler.cohorts import TenantCohort, get_tenant_cohort
from app.services.scheduler.processors import AnalysisProcessor

logger = structlog.get_logger()

# Arbitrary constant for scheduler advisory locks
# We use transaction-level locks to ensure they are released automatically
SCHEDULER_LOCK_BASE_ID = 48293021


# Prometheus Metrics
SCHEDULER_JOB_RUNS = Counter(
    "valdrix_scheduler_job_runs_total",
    "Total number of scheduled job runs",
    ["job_name", "status"]
)

SCHEDULER_JOB_DURATION = Histogram(
    "valdrix_scheduler_job_duration_seconds",
    "Duration of scheduled jobs in seconds",
    ["job_name"],
    buckets=[1, 5, 10, 30, 60, 120, 300, 600]
)

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
        """Enqueues analysis jobs for all tenants in a specific cohort."""
        import uuid
        job_id = str(uuid.uuid4())
        set_correlation_id(job_id)
        structlog.contextvars.bind_contextvars(correlation_id=job_id, job_type="scheduling", cohort=target_cohort.value)
        
        job_name = f"cohort_{target_cohort.value}_enqueue"
        start_time = time.time()

        try:
            async with self.session_maker() as db:
                async with db.begin():
                    lock_id = SCHEDULER_LOCK_BASE_ID + hash(target_cohort.value) % 1000
                    lock_check = await db.execute(
                        sa.text("SELECT pg_try_advisory_xact_lock(:id)"), 
                        {"id": lock_id}
                    )
                    if not lock_check.scalar():
                        logger.info("scheduler_cohort_enqueue_skipped_locked", cohort=target_cohort.value)
                        return
                    
                    # SQL-level Cohort Filtering
                    query = sa.select(Tenant)
                    if target_cohort == TenantCohort.HIGH_VALUE:
                        query = query.where(Tenant.plan.in_(["enterprise", "pro"]))

                    elif target_cohort == TenantCohort.ACTIVE:
                        query = query.where(Tenant.plan == "growth")
                    else: # DORMANT
                        query = query.where(Tenant.plan.in_(["starter", "trial"]))

                    result = await db.execute(query)
                    cohort_tenants = result.scalars().all()

                    if not cohort_tenants:
                        logger.info("scheduler_cohort_empty", cohort=target_cohort.value)
                        return

                    from app.services.jobs.processor import enqueue_job
                    from app.models.background_job import JobType

                    # We don't gather inside the transaction to avoid holding it too long
                    # but we need the jobs to stay in this transaction for consistency?
                    # Actually enqueue_job does its own commit. That's a problem.
                    # We should refactor enqueue_job to optionally take an existing session.
                    
                    # For now, we'll just insert them directly if in transaction
                    for tenant in cohort_tenants:
                        from app.models.background_job import BackgroundJob, JobStatus
                        db.add(BackgroundJob(
                            job_type=JobType.FINOPS_ANALYSIS.value,
                            tenant_id=tenant.id,
                            status=JobStatus.PENDING,
                            scheduled_for=datetime.now(timezone.utc),
                            created_at=datetime.now(timezone.utc)
                        ))
                        db.add(BackgroundJob(
                            job_type=JobType.ZOMBIE_SCAN.value,
                            tenant_id=tenant.id,
                            status=JobStatus.PENDING,
                            scheduled_for=datetime.now(timezone.utc),
                            created_at=datetime.now(timezone.utc)
                        ))
                        db.add(BackgroundJob(
                            job_type=JobType.COST_INGESTION.value,
                            tenant_id=tenant.id,
                            status=JobStatus.PENDING,
                            scheduled_for=datetime.now(timezone.utc),
                            created_at=datetime.now(timezone.utc)
                        ))

            SCHEDULER_JOB_RUNS.labels(job_name=job_name, status="success").inc()
            self._last_run_success = True
            self._last_run_time = datetime.now(timezone.utc).isoformat()

        except Exception as e:
            logger.error("scheduler_cohort_enqueue_failed", job=job_name, error=str(e))
            SCHEDULER_JOB_RUNS.labels(job_name=job_name, status="failure").inc()
            self._last_run_success = False
            self._last_run_time = datetime.now(timezone.utc).isoformat()
        finally:
            duration = time.time() - start_time
            SCHEDULER_JOB_DURATION.labels(job_name=job_name).observe(duration)

    async def auto_remediation_job(self):
        """Weekly autonomous remediation sweep (Enqueues jobs)."""
        import uuid
        job_id = str(uuid.uuid4())
        set_correlation_id(job_id)
        structlog.contextvars.bind_contextvars(correlation_id=job_id, job_type="scheduling_remediation")
        
        async with self.session_maker() as db:
            async with db.begin():
                # Advisory lock for remediation
                lock_id = SCHEDULER_LOCK_BASE_ID + 999
                lock_check = await db.execute(
                    sa.text("SELECT pg_try_advisory_xact_lock(:id)"), 
                    {"id": lock_id}
                )
                if not lock_check.scalar():
                    return

                result = await db.execute(sa.select(AWSConnection))

                connections = result.scalars().all()

                from app.models.background_job import BackgroundJob, JobType, JobStatus
                for conn in connections:
                    db.add(BackgroundJob(
                        job_type=JobType.REMEDIATION.value,
                        tenant_id=conn.tenant_id,
                        payload={"connection_id": str(conn.id), "region": conn.region},
                        status=JobStatus.PENDING,
                        scheduled_for=datetime.now(timezone.utc),
                        created_at=datetime.now(timezone.utc)
                    ))

    async def billing_sweep_job(self):
        """Daily sweep to find subscriptions due for renewal."""
        from app.services.billing.paystack_billing import TenantSubscription, SubscriptionStatus
        from app.models.background_job import BackgroundJob, JobType, JobStatus
        
        async with self.session_maker() as db:
            async with db.begin():
                # Find active subscriptions where next_payment_date is in the past
                query = sa.select(TenantSubscription).where(
                    TenantSubscription.status == SubscriptionStatus.ACTIVE.value,
                    TenantSubscription.next_payment_date <= datetime.now(timezone.utc),
                    TenantSubscription.paystack_auth_code.isnot(None)
                )
                result = await db.execute(query)
                due_subscriptions = result.scalars().all()

                for sub in due_subscriptions:
                    # Enqueue individual renewal job
                    db.add(BackgroundJob(
                        job_type=JobType.RECURRING_BILLING.value,
                        tenant_id=sub.tenant_id,
                        payload={"subscription_id": str(sub.id)},
                        status=JobStatus.PENDING,
                        scheduled_for=datetime.now(timezone.utc),
                        created_at=datetime.now(timezone.utc)
                    ))
                
                logger.info("billing_sweep_completed", due_count=len(due_subscriptions))

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
