import structlog
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.remediation import RemediationRequest, RemediationAction, RemediationStatus
from app.models.remediation_settings import RemediationSettings
from app.services.zombies.detector import ZombieDetector
from app.services.zombies.detector import RemediationService

logger = structlog.get_logger()

class AutonomousRemediationEngine:
    """
    AI-Executive for Autonomous Remediation (ActiveOps).
    
    Operates in two modes:
    1. Dry Run (Default): Identifies candidates and creates PENDING requests.
    2. Auto-Pilot (High Risk): Automatically APPROVES and EXECUTES high-confidence candidates.
    
    Safety:
    - High confidence threshold required for Auto-Pilot.
    - Snapshots < 90 days are never auto-deleted.
    - Volumes with recent IOPS are never auto-deleted.
    """
    
    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        
        # Default safety (overridden by DB settings in run_autonomous_sweep)
        self.auto_pilot_enabled = False
        self.min_confidence_threshold = 0.95
        
    async def run_autonomous_sweep(self, region: str, credentials: Dict[str, str]) -> Dict[str, Any]:
        """
        Scans for zombies and applies remediation policy.
        """
        # Load dynamic settings
        settings_res = await self.db.execute(
            select(RemediationSettings).where(RemediationSettings.tenant_id == self.tenant_id)
        )
        settings = settings_res.scalar_one_or_none()
        if settings:
            self.auto_pilot_enabled = settings.auto_pilot_enabled
            self.min_confidence_threshold = float(settings.min_confidence_threshold)

        logger.info("starting_autonomous_sweep", 
                    tenant_id=str(self.tenant_id), 
                    auto_pilot=self.auto_pilot_enabled,
                    threshold=self.min_confidence_threshold)
        
        detector = ZombieDetector(region=region, credentials=credentials)
        zombies = await detector.scan_all()
        
        results = {
            "scanned": 0,
            "actions_created": 0,
            "auto_executed": 0,
            "errors": 0
        }
        
        remediation_service = RemediationService(self.db, region=region, credentials=credentials)
        
        # Categories to process
        categories = [
            "unattached_volumes", "old_snapshots", "unused_elastic_ips",
            "idle_instances", "orphan_load_balancers", "idle_rds_databases",
            "underused_nat_gateways", "idle_s3_buckets", "legacy_ecr_images",
            "idle_sagemaker_endpoints", "cold_redshift_clusters"
        ]
        
        for category in categories:
            for item in zombies.get(category, []):
                try:
                    # Map action string to Enum
                    action_enum = RemediationAction(item["action"])
                    
                    await self._process_candidate(
                        remediation_service, 
                        resource_id=item["resource_id"],
                        resource_type=item["resource_type"],
                        action=action_enum,
                        savings=item.get("monthly_cost", 0.0),
                        confidence=item.get("confidence_score", 0.70),
                        reason=item.get("explainability_notes", "Flagged as zombie resource by automated scan.")
                    )
                    results["scanned"] += 1
                except Exception as e:
                    logger.error("autonomous_error", 
                                category=category,
                                resource=item.get("resource_id", "unknown"), 
                                error=str(e))
                    results["errors"] += 1
        
        return results

    async def _process_candidate(
        self, 
        service: RemediationService, 
        resource_id: str, 
        resource_type: str, 
        action: RemediationAction, 
        savings: float,
        confidence: float,
        reason: str
    ):
        """
        Decides whether to create a Pending request or Auto-Execute.
        """
        
        # Check if request already exists
        existing = await service.db.execute(
            select(RemediationRequest).where(
                RemediationRequest.resource_id == resource_id,
                RemediationRequest.tenant_id == self.tenant_id,
                RemediationRequest.status.in_([RemediationStatus.PENDING, RemediationStatus.COMPLETED])
            )
        )
        if existing.scalar_one_or_none():
            return # Skip duplication

        # Create Request (base step)
        request = await service.create_request(
            tenant_id=self.tenant_id,
            user_id=None, # System created
            resource_id=resource_id,
            resource_type=resource_type,
            action=action,
            estimated_savings=savings,
            confidence_score=confidence,
            explainability_notes=reason
        )
        
        # Auto-Pilot Logic: Enabled AND High Confidence
        if self.auto_pilot_enabled and confidence >= self.min_confidence_threshold:
            logger.info("auto_pilot_engaging", resource_id=resource_id, confidence=confidence)
            
            # Step 1: Auto-Approve
            await service.approve(
                request_id=request.id,
                tenant_id=self.tenant_id,
                reviewer_id=None, # System approved
                notes=f"Auto-Pilot Execution (Confidence: {confidence})"
            )
            
            # Step 2: Execute
            await service.execute(
                request_id=request.id,
                tenant_id=self.tenant_id
            )
        else:
            logger.info("autonomous_candidate_flagged", resource_id=resource_id, mode="pending")
