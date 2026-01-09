"""
Zombie Resource Detector & Remediator

Full production implementation with:
1. Zombie detection (unattached volumes, old snapshots, unused EIPs)
2. Approval workflow (pending → approved → executed)
3. Safe delete with backup option
4. Audit trail for compliance

Uses AWS CloudWatch, EC2, and Cost Explorer APIs.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID
import boto3
from botocore.exceptions import ClientError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.models.remediation import RemediationRequest, RemediationStatus, RemediationAction

logger = structlog.get_logger()


# Estimated monthly costs for common resources
ESTIMATED_COSTS = {
    "ebs_volume_gb": 0.10,       # $0.10/GB/month for gp2
    "elastic_ip": 3.65,          # $0.005/hour * 730 hours
    "snapshot_gb": 0.05,         # $0.05/GB/month
    "ec2_t3_micro": 7.59,        # t3.micro monthly
    "ec2_t3_small": 15.18,       # t3.small monthly
    "ec2_t3_medium": 30.37,      # t3.medium monthly
    "ec2_m5_large": 69.12,       # m5.large monthly
    "ec2_default": 30.00,        # Default estimate
    "elb": 16.43,                # ALB base cost
}


class ZombieDetector:
    """
    Detects zombie (unused/underutilized) AWS resources.
    
    Usage:
        detector = ZombieDetector()
        zombies = await detector.scan_all()
        
    For multi-tenant (uses STS credentials):
        detector = ZombieDetector(region=region, credentials=creds)
    """
    
    def __init__(self, region: str = "us-east-1", credentials: Dict[str, str] = None):
        self.region = region
        self.credentials = credentials
        
        # Use provided credentials (from STS AssumeRole) or default
        if credentials:
            self.ec2 = boto3.client(
                "ec2", 
                region_name=region,
                aws_access_key_id=credentials["AccessKeyId"],
                aws_secret_access_key=credentials["SecretAccessKey"],
                aws_session_token=credentials["SessionToken"],
            )
            self.cloudwatch = boto3.client(
                "cloudwatch", 
                region_name=region,
                aws_access_key_id=credentials["AccessKeyId"],
                aws_secret_access_key=credentials["SecretAccessKey"],
                aws_session_token=credentials["SessionToken"],
            )
            self.elb = boto3.client(
                "elbv2", 
                region_name=region,
                aws_access_key_id=credentials["AccessKeyId"],
                aws_secret_access_key=credentials["SecretAccessKey"],
                aws_session_token=credentials["SessionToken"],
            )
            self.rds = boto3.client(
                "rds",
                region_name=region,
                aws_access_key_id=credentials["AccessKeyId"],
                aws_secret_access_key=credentials["SecretAccessKey"],
                aws_session_token=credentials["SessionToken"],
            )
        else:
            # Default to environment credentials
            self.ec2 = boto3.client("ec2", region_name=region)
            self.cloudwatch = boto3.client("cloudwatch", region_name=region)
            self.elb = boto3.client("elbv2", region_name=region)
            self.rds = boto3.client("rds", region_name=region)
    
    async def scan_all(self) -> Dict[str, Any]:
        """
        Scan for all types of zombie resources.
        
        Returns dict with zombies by category and total waste estimate.
        """
        zombies = {
            "unattached_volumes": [],
            "old_snapshots": [],
            "unused_elastic_ips": [],
            "idle_instances": [],
            "orphan_load_balancers": [],
            "idle_rds_databases": [],
            "underused_nat_gateways": [],
            "total_monthly_waste": Decimal("0"),
            "region": self.region,
            "scanned_at": datetime.utcnow().isoformat(),
        }
        
        try:
            # Storage zombies
            zombies["unattached_volumes"] = self._find_unattached_volumes()
            zombies["old_snapshots"] = self._find_old_snapshots()
            zombies["unused_elastic_ips"] = self._find_unused_elastic_ips()
            
            # Compute zombies
            zombies["idle_instances"] = self._find_idle_instances()
            
            # Network zombies
            zombies["orphan_load_balancers"] = self._find_orphan_load_balancers()
            zombies["underused_nat_gateways"] = self._find_underused_nat_gateways()
            
            # Database zombies
            zombies["idle_rds_databases"] = self._find_idle_rds_databases()
            
            # Calculate total waste
            total = Decimal("0")
            for category in ["unattached_volumes", "old_snapshots", "unused_elastic_ips", 
                           "idle_instances", "orphan_load_balancers", "idle_rds_databases",
                           "underused_nat_gateways"]:
                for item in zombies.get(category, []):
                    total += Decimal(str(item.get("monthly_cost", 0)))
            
            zombies["total_monthly_waste"] = float(round(total, 2))
            
            logger.info(
                "zombie_scan_complete",
                volumes=len(zombies["unattached_volumes"]),
                snapshots=len(zombies["old_snapshots"]),
                eips=len(zombies["unused_elastic_ips"]),
                idle_ec2=len(zombies["idle_instances"]),
                orphan_lbs=len(zombies["orphan_load_balancers"]),
                idle_rds=len(zombies["idle_rds_databases"]),
                waste=zombies["total_monthly_waste"],
            )
            
        except ClientError as e:
            logger.error("zombie_scan_failed", error=str(e))
            zombies["error"] = str(e)
        
        return zombies
    
    def _find_unattached_volumes(self) -> List[Dict[str, Any]]:
        """Find EBS volumes not attached to any instance."""
        zombies = []
        
        try:
            response = self.ec2.describe_volumes(
                Filters=[{"Name": "status", "Values": ["available"]}]
            )
            
            for vol in response.get("Volumes", []):
                size_gb = vol.get("Size", 0)
                monthly_cost = size_gb * ESTIMATED_COSTS["ebs_volume_gb"]
                backup_cost = size_gb * ESTIMATED_COSTS["snapshot_gb"]
                
                zombies.append({
                    "resource_id": vol["VolumeId"],
                    "resource_type": "EBS Volume",
                    "size_gb": size_gb,
                    "monthly_cost": round(monthly_cost, 2),
                    "backup_cost_monthly": round(backup_cost, 2),
                    "created": vol["CreateTime"].isoformat(),
                    "recommendation": "Delete if no longer needed",
                    "action": "delete_volume",
                    "supports_backup": True,
                })
        except ClientError as e:
            logger.warning("volume_scan_error", error=str(e))
        
        return zombies
    
    def _find_old_snapshots(self, days_old: int = 90) -> List[Dict[str, Any]]:
        """Find EBS snapshots older than threshold."""
        zombies = []
        cutoff = datetime.utcnow() - timedelta(days=days_old)
        
        try:
            response = self.ec2.describe_snapshots(OwnerIds=["self"])
            
            for snap in response.get("Snapshots", []):
                start_time = snap.get("StartTime")
                if start_time and start_time.replace(tzinfo=None) < cutoff:
                    size_gb = snap.get("VolumeSize", 0)
                    monthly_cost = size_gb * ESTIMATED_COSTS["snapshot_gb"]
                    
                    zombies.append({
                        "resource_id": snap["SnapshotId"],
                        "resource_type": "EBS Snapshot",
                        "size_gb": size_gb,
                        "age_days": (datetime.utcnow() - start_time.replace(tzinfo=None)).days,
                        "monthly_cost": round(monthly_cost, 2),
                        "backup_cost_monthly": 0,
                        "recommendation": "Delete if backup no longer needed",
                        "action": "delete_snapshot",
                        "supports_backup": False,
                    })
        except ClientError as e:
            logger.warning("snapshot_scan_error", error=str(e))
        
        return zombies
    
    def _find_unused_elastic_ips(self) -> List[Dict[str, Any]]:
        """Find Elastic IPs not associated with any instance."""
        zombies = []
        
        try:
            response = self.ec2.describe_addresses()
            
            for addr in response.get("Addresses", []):
                if not addr.get("InstanceId") and not addr.get("NetworkInterfaceId"):
                    zombies.append({
                        "resource_id": addr.get("AllocationId", addr.get("PublicIp")),
                        "resource_type": "Elastic IP",
                        "public_ip": addr.get("PublicIp"),
                        "monthly_cost": ESTIMATED_COSTS["elastic_ip"],
                        "backup_cost_monthly": 0,
                        "recommendation": "Release if not needed",
                        "action": "release_elastic_ip",
                        "supports_backup": False,
                    })
        except ClientError as e:
            logger.warning("eip_scan_error", error=str(e))
        
        return zombies
    
    def _find_idle_instances(self, cpu_threshold: float = 5.0, days: int = 7) -> List[Dict[str, Any]]:
        """
        Find EC2 instances with avg CPU < threshold over specified days.
        
        Args:
            cpu_threshold: Maximum CPU % to be considered idle (default 5%)
            days: Number of days to check (default 7)
        """
        zombies = []
        
        try:
            # Get running instances
            response = self.ec2.describe_instances(
                Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
            )
            
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(days=days)
            
            for reservation in response.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    instance_id = instance["InstanceId"]
                    instance_type = instance.get("InstanceType", "unknown")
                    
                    try:
                        # Get CPU utilization metrics
                        metrics = self.cloudwatch.get_metric_statistics(
                            Namespace="AWS/EC2",
                            MetricName="CPUUtilization",
                            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                            StartTime=start_time,
                            EndTime=end_time,
                            Period=86400,  # 1 day
                            Statistics=["Average"]
                        )
                        
                        datapoints = metrics.get("Datapoints", [])
                        if datapoints:
                            avg_cpu = sum(d["Average"] for d in datapoints) / len(datapoints)
                            if avg_cpu < cpu_threshold:
                                # Estimate cost based on instance type
                                cost_key = f"ec2_{instance_type.replace('.', '_')}"
                                monthly_cost = ESTIMATED_COSTS.get(cost_key, ESTIMATED_COSTS["ec2_default"])
                                
                                zombies.append({
                                    "resource_id": instance_id,
                                    "resource_type": "EC2 Instance",
                                    "instance_type": instance_type,
                                    "avg_cpu_percent": round(avg_cpu, 2),
                                    "monthly_cost": round(monthly_cost, 2),
                                    "launch_time": instance.get("LaunchTime", "").isoformat() if instance.get("LaunchTime") else "",
                                    "recommendation": "Stop or terminate if not needed",
                                    "action": "stop_instance",
                                    "supports_backup": True,
                                })
                    except ClientError:
                        pass  # Skip instances where metrics aren't available
                        
        except ClientError as e:
            logger.warning("idle_instance_scan_error", error=str(e))
        
        return zombies
    
    def _find_orphan_load_balancers(self) -> List[Dict[str, Any]]:
        """Find ALBs/NLBs with no healthy targets."""
        zombies = []
        
        try:
            lbs = self.elb.describe_load_balancers()
            
            for lb in lbs.get("LoadBalancers", []):
                lb_arn = lb["LoadBalancerArn"]
                lb_name = lb["LoadBalancerName"]
                lb_type = lb.get("Type", "application")
                
                try:
                    # Get target groups for this LB
                    target_groups = self.elb.describe_target_groups(
                        LoadBalancerArn=lb_arn
                    )
                    
                    has_healthy_targets = False
                    for tg in target_groups.get("TargetGroups", []):
                        health = self.elb.describe_target_health(
                            TargetGroupArn=tg["TargetGroupArn"]
                        )
                        healthy = [t for t in health.get("TargetHealthDescriptions", [])
                                  if t.get("TargetHealth", {}).get("State") == "healthy"]
                        if healthy:
                            has_healthy_targets = True
                            break
                    
                    if not has_healthy_targets:
                        zombies.append({
                            "resource_id": lb_name,
                            "resource_arn": lb_arn,
                            "resource_type": "Load Balancer",
                            "lb_type": lb_type,
                            "monthly_cost": ESTIMATED_COSTS["elb"],
                            "recommendation": "Delete if no longer needed",
                            "action": "delete_load_balancer",
                            "supports_backup": False,
                        })
                except ClientError:
                    pass  # Skip LBs where target group info isn't available
                    
        except ClientError as e:
            logger.warning("orphan_lb_scan_error", error=str(e))
        
        return zombies
    
    def _find_idle_rds_databases(self, connection_threshold: int = 1, days: int = 7) -> List[Dict[str, Any]]:
        """
        Find RDS instances with < threshold connections over specified days.
        
        Args:
            connection_threshold: Max avg connections to be considered idle (default 1)
            days: Number of days to check (default 7)
        """
        zombies = []
        
        try:
            response = self.rds.describe_db_instances()
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(days=days)
            
            for db in response.get("DBInstances", []):
                db_id = db["DBInstanceIdentifier"]
                db_class = db.get("DBInstanceClass", "unknown")
                engine = db.get("Engine", "unknown")
                
                try:
                    metrics = self.cloudwatch.get_metric_statistics(
                        Namespace="AWS/RDS",
                        MetricName="DatabaseConnections",
                        Dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}],
                        StartTime=start_time,
                        EndTime=end_time,
                        Period=86400,
                        Statistics=["Average"]
                    )
                    
                    datapoints = metrics.get("Datapoints", [])
                    if datapoints:
                        avg_connections = sum(d["Average"] for d in datapoints) / len(datapoints)
                        if avg_connections < connection_threshold:
                            # Estimate monthly cost based on instance class
                            # db.t3.micro ~ $12/mo, db.r5.large ~ $180/mo
                            if "micro" in db_class:
                                monthly_cost = 12.00
                            elif "small" in db_class:
                                monthly_cost = 25.00
                            elif "medium" in db_class:
                                monthly_cost = 50.00
                            elif "large" in db_class:
                                monthly_cost = 100.00
                            elif "xlarge" in db_class:
                                monthly_cost = 200.00
                            else:
                                monthly_cost = 75.00  # Default
                            
                            zombies.append({
                                "resource_id": db_id,
                                "resource_type": "RDS Database",
                                "db_class": db_class,
                                "engine": engine,
                                "avg_connections": round(avg_connections, 2),
                                "monthly_cost": round(monthly_cost, 2),
                                "recommendation": "Stop or delete if not needed",
                                "action": "stop_rds_instance",
                                "supports_backup": True,
                            })
                except ClientError:
                    pass  # Skip DBs where metrics aren't available
                    
        except ClientError as e:
            logger.warning("idle_rds_scan_error", error=str(e))
        
        return zombies
    
    def _find_underused_nat_gateways(self, gb_threshold: float = 1.0, days: int = 30) -> List[Dict[str, Any]]:
        """
        Find NAT Gateways with < threshold GB data processed.
        NAT Gateway costs $32.40/month base + data processing.
        
        Args:
            gb_threshold: Max GB processed to be considered underused (default 1.0)
            days: Number of days to check (default 30)
        """
        zombies = []
        
        try:
            response = self.ec2.describe_nat_gateways(
                Filters=[{"Name": "state", "Values": ["available"]}]
            )
            
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(days=days)
            
            for nat in response.get("NatGateways", []):
                nat_id = nat["NatGatewayId"]
                vpc_id = nat.get("VpcId", "unknown")
                
                try:
                    metrics = self.cloudwatch.get_metric_statistics(
                        Namespace="AWS/NATGateway",
                        MetricName="BytesOutToDestination",
                        Dimensions=[{"Name": "NatGatewayId", "Value": nat_id}],
                        StartTime=start_time,
                        EndTime=end_time,
                        Period=86400 * days,  # Sum over entire period
                        Statistics=["Sum"]
                    )
                    
                    datapoints = metrics.get("Datapoints", [])
                    total_bytes = sum(d.get("Sum", 0) for d in datapoints)
                    total_gb = total_bytes / (1024**3)
                    
                    if total_gb < gb_threshold:
                        zombies.append({
                            "resource_id": nat_id,
                            "resource_type": "NAT Gateway",
                            "vpc_id": vpc_id,
                            "data_processed_gb": round(total_gb, 4),
                            "monthly_cost": 32.40,  # Base cost
                            "recommendation": "Consider VPC endpoints or smaller NAT",
                            "action": "delete_nat_gateway",
                            "supports_backup": False,
                        })
                except ClientError:
                    pass  # Skip NATs where metrics aren't available
                    
        except ClientError as e:
            logger.warning("nat_gateway_scan_error", error=str(e))
        
        return zombies


class RemediationService:
    """
    Manages the remediation approval workflow.
    
    Workflow:
    1. create_request() - User requests remediation
    2. list_pending() - Reviewer sees pending requests  
    3. approve() / reject() - Reviewer takes action
    4. execute() - System executes approved requests
    """
    
    def __init__(self, db: AsyncSession, region: str = "us-east-1"):
        self.db = db
        self.region = region
        self.ec2 = boto3.client("ec2", region_name=region)
    
    async def create_request(
        self,
        tenant_id: UUID,
        user_id: UUID,
        resource_id: str,
        resource_type: str,
        action: RemediationAction,
        estimated_savings: float,
        create_backup: bool = False,
        backup_retention_days: int = 30,
        backup_cost_estimate: float = 0,
    ) -> RemediationRequest:
        """
        Create a new remediation request (pending approval).
        """
        request = RemediationRequest(
            tenant_id=tenant_id,
            resource_id=resource_id,
            resource_type=resource_type,
            region=self.region,
            action=action,
            status=RemediationStatus.PENDING,
            estimated_monthly_savings=Decimal(str(estimated_savings)),
            create_backup=create_backup,
            backup_retention_days=backup_retention_days,
            backup_cost_estimate=Decimal(str(backup_cost_estimate)) if backup_cost_estimate else None,
            requested_by_user_id=user_id,
        )
        
        self.db.add(request)
        await self.db.commit()
        await self.db.refresh(request)
        
        logger.info(
            "remediation_request_created",
            request_id=str(request.id),
            resource=resource_id,
            action=action.value,
            backup=create_backup,
        )
        
        return request
    
    async def list_pending(self, tenant_id: UUID) -> List[RemediationRequest]:
        """List all pending remediation requests for a tenant."""
        result = await self.db.execute(
            select(RemediationRequest)
            .where(RemediationRequest.tenant_id == tenant_id)
            .where(RemediationRequest.status == RemediationStatus.PENDING)
            .order_by(RemediationRequest.created_at.desc())
        )
        return list(result.scalars().all())
    
    async def approve(
        self,
        request_id: UUID,
        reviewer_id: UUID,
        notes: Optional[str] = None,
    ) -> RemediationRequest:
        """
        Approve a remediation request.
        Does NOT execute yet - that's a separate step for safety.
        """
        result = await self.db.execute(
            select(RemediationRequest).where(RemediationRequest.id == request_id)
        )
        request = result.scalar_one_or_none()
        
        if not request:
            raise ValueError(f"Request {request_id} not found")
        
        if request.status != RemediationStatus.PENDING:
            raise ValueError(f"Request is {request.status.value}, not pending")
        
        request.status = RemediationStatus.APPROVED
        request.reviewed_by_user_id = reviewer_id
        request.review_notes = notes
        
        await self.db.commit()
        await self.db.refresh(request)
        
        logger.info(
            "remediation_approved",
            request_id=str(request_id),
            reviewer=str(reviewer_id),
        )
        
        return request
    
    async def reject(
        self,
        request_id: UUID,
        reviewer_id: UUID,
        notes: Optional[str] = None,
    ) -> RemediationRequest:
        """Reject a remediation request."""
        result = await self.db.execute(
            select(RemediationRequest).where(RemediationRequest.id == request_id)
        )
        request = result.scalar_one_or_none()
        
        if not request:
            raise ValueError(f"Request {request_id} not found")
        
        request.status = RemediationStatus.REJECTED
        request.reviewed_by_user_id = reviewer_id
        request.review_notes = notes
        
        await self.db.commit()
        await self.db.refresh(request)
        
        logger.info(
            "remediation_rejected",
            request_id=str(request_id),
            reviewer=str(reviewer_id),
        )
        
        return request
    
    async def execute(self, request_id: UUID) -> RemediationRequest:
        """
        Execute an approved remediation request.
        
        If create_backup is True, creates snapshot before deleting volume.
        """
        result = await self.db.execute(
            select(RemediationRequest).where(RemediationRequest.id == request_id)
        )
        request = result.scalar_one_or_none()
        
        if not request:
            raise ValueError(f"Request {request_id} not found")
        
        if request.status != RemediationStatus.APPROVED:
            raise ValueError(f"Request must be approved first (current: {request.status.value})")
        
        request.status = RemediationStatus.EXECUTING
        await self.db.commit()
        
        try:
            # Create backup if requested (for volumes only)
            if request.create_backup and request.action == RemediationAction.DELETE_VOLUME:
                backup_id = await self._create_volume_backup(
                    request.resource_id,
                    request.backup_retention_days,
                )
                request.backup_resource_id = backup_id
            
            # Execute the action
            await self._execute_action(request.resource_id, request.action)
            
            request.status = RemediationStatus.COMPLETED
            logger.info(
                "remediation_executed",
                request_id=str(request_id),
                resource=request.resource_id,
            )
            
        except Exception as e:
            request.status = RemediationStatus.FAILED
            request.execution_error = str(e)[:500]
            logger.error(
                "remediation_failed",
                request_id=str(request_id),
                error=str(e),
            )
        
        await self.db.commit()
        await self.db.refresh(request)
        return request
    
    async def _create_volume_backup(
        self,
        volume_id: str,
        retention_days: int,
    ) -> str:
        """Create a snapshot backup before deleting a volume."""
        try:
            response = self.ec2.create_snapshot(
                VolumeId=volume_id,
                Description=f"Backup before remediation - retain {retention_days} days",
                TagSpecifications=[
                    {
                        "ResourceType": "snapshot",
                        "Tags": [
                            {"Key": "CloudSentinel", "Value": "remediation-backup"},
                            {"Key": "RetentionDays", "Value": str(retention_days)},
                            {"Key": "OriginalVolume", "Value": volume_id},
                        ],
                    }
                ],
            )
            
            backup_id = response["SnapshotId"]
            logger.info(
                "backup_created",
                volume_id=volume_id,
                snapshot_id=backup_id,
            )
            return backup_id
            
        except ClientError as e:
            logger.error("backup_creation_failed", volume_id=volume_id, error=str(e))
            raise
    
    async def _execute_action(
        self,
        resource_id: str,
        action: RemediationAction,
    ) -> None:
        """Execute the actual AWS action."""
        try:
            if action == RemediationAction.DELETE_VOLUME:
                self.ec2.delete_volume(VolumeId=resource_id)
                
            elif action == RemediationAction.DELETE_SNAPSHOT:
                self.ec2.delete_snapshot(SnapshotId=resource_id)
                
            elif action == RemediationAction.RELEASE_ELASTIC_IP:
                self.ec2.release_address(AllocationId=resource_id)
                
            elif action == RemediationAction.STOP_INSTANCE:
                self.ec2.stop_instances(InstanceIds=[resource_id])
                
            elif action == RemediationAction.TERMINATE_INSTANCE:
                self.ec2.terminate_instances(InstanceIds=[resource_id])
                
            else:
                raise ValueError(f"Unknown action: {action}")
                
        except ClientError as e:
            logger.error("aws_action_failed", resource=resource_id, error=str(e))
            raise
