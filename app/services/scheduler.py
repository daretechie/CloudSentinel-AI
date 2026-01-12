from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import date, timedelta, datetime, timezone
import time
import structlog
from prometheus_client import Counter, Histogram
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

import asyncio
from app.services.adapters.aws_multitenant import MultiTenantAWSAdapter
from app.services.llm.factory import LLMFactory
from app.services.llm.analyzer import FinOpsAnalyzer
from app.services.carbon.calculator import CarbonCalculator
from app.services.zombies.detector import ZombieDetector
from app.models.tenant import Tenant
from app.models.aws_connection import AWSConnection
from app.core.config import get_settings

logger = structlog.get_logger()

# Prometheus Metrics
SCHEDULER_JOB_RUNS = Counter(
    "valdrix_scheduler_job_runs_total",
    "Total number of scheduled job runs",
    ["job_name", "status"]  # status: success, failure
)

SCHEDULER_JOB_DURATION = Histogram(
    "valdrix_scheduler_job_duration_seconds",
    "Duration of scheduled jobs in seconds",
    ["job_name"],
    buckets=[1, 5, 10, 30, 60, 120, 300, 600]  # Up to 10 minutes
)


class SchedulerService:
    """
    Background job scheduler for Valdrix.
    
    Uses APScheduler with AsyncIOScheduler for non-blocking job execution.
    Receives session_maker via dependency injection for proper connection pooling.
    """
    
    def __init__(self, session_maker: async_sessionmaker[AsyncSession]):
        """
        Initialize the scheduler with an injected session factory.
        
        Args:
            session_maker: SQLAlchemy async session factory (from app.db.session)
        """
        self.scheduler = AsyncIOScheduler()
        self.settings = get_settings()
        self._last_run_success: bool | None = None
        self._last_run_time: str | None = None
        
        # Use injected session factory (shared with FastAPI)
        self.session_maker = session_maker
        self.semaphore = asyncio.Semaphore(10)  # Limit concurrency to 10 tenants

    async def daily_analysis_job(self):
        """
        Multitenant analysis job.
        Iterates through all tenants -> Analyzes each -> Logs/Notify.
        """
        job_name = "daily_finops_scan"
        start_time = time.time()
        
        logger.info("scheduler_job_starting", job=job_name)

        try:
            # 1. Get all tenants using a short-lived session
            async with self.session_maker() as db:
                result = await db.execute(select(Tenant))
                tenants = result.scalars().all()
                
            logger.info("scheduler_scanning_tenants", count=len(tenants))
            
            today = date.today()
            yesterday = today - timedelta(days=1)
            
            # Process tenants in parallel with a semaphore limit
            # Note: Each task will open its OWN session now
            tasks = [self._process_tenant_wrapper(tenant, yesterday, today) for tenant in tenants]
            await asyncio.gather(*tasks)

            SCHEDULER_JOB_RUNS.labels(job_name=job_name, status="success").inc()
            self._last_run_success = True
            self._last_run_time = datetime.now(timezone.utc).isoformat()

        except Exception as e:
            logger.error("scheduler_job_failed", job=job_name, error=str(e))
            SCHEDULER_JOB_RUNS.labels(job_name=job_name, status="failure").inc()
            self._last_run_success = False
            self._last_run_time = datetime.now(timezone.utc).isoformat()
            # Don't raise, let the loop handle individual tenant failures

        finally:
            duration = time.time() - start_time
            SCHEDULER_JOB_DURATION.labels(job_name=job_name).observe(duration)
            logger.info("scheduler_job_duration", job=job_name, seconds=round(duration, 2))

    async def _process_tenant_wrapper(self, tenant: Tenant, start_date: date, end_date: date):
        """Wrapper to apply semaphore to tenant processing."""
        async with self.semaphore:
            # Critical: Create a NEW session for this task to avoid shared state corruption
            async with self.session_maker() as db:
                await self._process_tenant(db, tenant, start_date, end_date)

    async def _process_tenant(self, db: AsyncSession, tenant: Tenant, start_date: date, end_date: date):
        """Process a single tenant's analysis."""
        from app.models.notification_settings import NotificationSettings
        
        try:
            logger.info("processing_tenant", tenant_id=str(tenant.id), name=tenant.name)
            
            # 1. Check Notification Settings
            result = await db.execute(
                select(NotificationSettings).where(NotificationSettings.tenant_id == tenant.id)
            )
            notif_settings = result.scalar_one_or_none()
            
            # Logic: If digest is disabled, we still perform analysis (for dashboard)
            # but we skip the "Notify" step.
            # In a more advanced version, we'd check if it's the right "hour" or "day"
            # for the tenant's specific schedule.
            
            # 2. Get AWS connections for this tenant
            result = await db.execute(
                select(AWSConnection).where(AWSConnection.tenant_id == tenant.id)
            )
            connections = result.scalars().all()
            
            if not connections:
                logger.info("tenant_no_connections", tenant_id=str(tenant.id))
                return

            llm = LLMFactory.create(self.settings.LLM_PROVIDER)
            analyzer = FinOpsAnalyzer(llm)
            carbon_calc = CarbonCalculator()
            
            for conn in connections:
                try:
                    # Use MultiTenant adapter
                    adapter = MultiTenantAWSAdapter(conn)
                    costs = await adapter.get_daily_costs(start_date, end_date)
                    
                    if not costs:
                        continue

                    # 1. LLM Analysis
                    # analyzer internally records usage to DB
                    await analyzer.analyze(costs, tenant_id=tenant.id, db=db)
                    
                    # 2. Carbon Calculation
                    carbon_result = carbon_calc.calculate_from_costs(costs, region=conn.region)
                    
                    # 3. Zombie Detection
                    creds = await adapter._get_credentials()
                    detector = ZombieDetector(region=conn.region, credentials=creds)
                    zombie_result = await detector.scan_all()
                    
                    # 4. Notify if enabled in settings
                    if notif_settings and notif_settings.slack_enabled:
                        # Only send digest if configured (daily or weekly)
                        if notif_settings.digest_schedule in ["daily", "weekly"]:
                            settings = get_settings()
                            if settings.SLACK_BOT_TOKEN and settings.SLACK_CHANNEL_ID:
                                # In multi-tenant, channel might be overriden
                                channel = notif_settings.slack_channel_override or settings.SLACK_CHANNEL_ID
                                
                                from app.services.notifications import SlackService
                                slack = SlackService(settings.SLACK_BOT_TOKEN, channel)
                                
                                zombie_count = sum(len(items) for items in zombie_result.values() if isinstance(items, list))
                                
                                # Calculate total cost for digest from the costs list
                                # corrected parsing logic for AWS CE response
                                total_cost = 0.0
                                for day in costs:
                                    total_cost += float(day.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0))
                                
                                await slack.send_digest({
                                    "tenant_name": tenant.name,
                                    "total_cost": total_cost,
                                    "carbon_kg": carbon_result.get("total_co2_kg", 0),
                                    "zombie_count": zombie_count,
                                    "period": f"{start_date.isoformat()} - {end_date.isoformat()}"
                                })

                except Exception as e:
                    logger.error("tenant_connection_failed", tenant_id=str(tenant.id), connection_id=str(conn.id), error=str(e))

        except Exception as e:
            logger.error("tenant_processing_failed", tenant_id=str(tenant.id), error=str(e))

    def start(self):
        """
        Start the scheduler.
        """
        # Get schedule from settings (with defaults)
        hour = self.settings.SCHEDULER_HOUR
        minute = self.settings.SCHEDULER_MINUTE
        
        trigger = CronTrigger(hour=hour, minute=minute, timezone="UTC")

        self.scheduler.add_job(
            self.daily_analysis_job,
            trigger=trigger,
            id="daily_finops_scan",
            replace_existing=True,
            max_instances=1,  # Prevent overlapping runs
            misfire_grace_time=3600,  # 1 hour grace period for missed jobs
        )
        
        # Weekly Auto-Remediation (Friday 8PM)
        remediation_trigger = CronTrigger(day_of_week="fri", hour=20, minute=0, timezone="UTC")
        self.scheduler.add_job(
            self.auto_remediation_job,
            trigger=remediation_trigger,
            id="weekly_remediation_sweep",
            replace_existing=True,
            max_instances=1
        )

        
        self.scheduler.start()

    async def auto_remediation_job(self):
        """
        Weekly job: Runs autonomous remediation engine in Dry-Run or Auto-Pilot mode.
        """
        # 1. Get all connections
        async with self.session_maker() as db:
            result = await db.execute(select(AWSConnection))
            connections = result.scalars().all()
            
        logger.info("scheduler_remediating_connections", count=len(connections))
        
        # Limit concurrency to avoid API throttling
        sema = asyncio.Semaphore(5)
        
        async def sema_wrapper(conn):
            async with sema:
                # Open NEW session per remediation task
                async with self.session_maker() as db:
                    await self._run_single_tenant_remediation(db, conn)

        tasks = [sema_wrapper(conn) for conn in connections]
        await asyncio.gather(*tasks)
                
        logger.info("scheduler_auto_remediation_complete")

    async def _run_single_tenant_remediation(self, db, connection):
        """Execute remediation for a single tenant."""
        from app.services.remediation.autonomous import AutonomousRemediationEngine
        from app.services.adapters.aws_multitenant import MultiTenantAWSAdapter
        
        tenant_id = connection.tenant_id
        # Default to DRY RUN for safety until fully production ready
        
        try:
            adapter = MultiTenantAWSAdapter(connection)
            creds = await adapter._get_credentials()
            
            engine = AutonomousRemediationEngine(db, tenant_id)
            result = await engine.run_autonomous_sweep(
                region=connection.region,
                credentials=creds
            )
            logger.info("tenant_remediation_complete", tenant=str(tenant_id), stats=result)
        except Exception as e:
            logger.error("tenant_remediation_failed", tenant=str(tenant_id), error=str(e))

    def stop(self):
        """
        Stop the scheduler gracefully, waiting for running jobs.
        """
        self.scheduler.shutdown(wait=True)
        logger.info("scheduler_stopped")

    def get_status(self) -> dict:
        """
        Return scheduler status for health checks.
        """
        return {
            "running": self.scheduler.running,
            "last_run_success": self._last_run_success,
            "last_run_time": self._last_run_time,
            "jobs": [job.id for job in self.scheduler.get_jobs()]
        }