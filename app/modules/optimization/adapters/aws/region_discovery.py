"""
Dynamic AWS Region Discovery

Implements the 2026 best practice of dynamic region discovery:
1. Phase 1: Get enabled regions via EC2 describe_regions
2. Phase 2: Filter by activity via Cost Explorer GetDimensionValues

This replaces hardcoded region lists and optimizes API calls by only
scanning regions with actual resources/costs.
"""

import aioboto3
from datetime import date, timedelta
from typing import List, Dict
import structlog
from botocore.exceptions import ClientError

logger = structlog.get_logger()


class RegionDiscovery:
    """
    Dynamically discovers AWS regions based on account configuration and activity.

    Use `get_hot_regions()` for daily scans (regions with recent costs).
    Use `get_enabled_regions()` for weekly scans (catch new deployments).
    """

    def __init__(self, credentials: Dict[str, str] = None):
        self.credentials = credentials
        self.session = aioboto3.Session()
        self._cached_enabled_regions: List[str] = []
        self._cached_hot_regions: List[str] = []

    async def get_enabled_regions(self) -> List[str]:
        """
        Get all regions enabled for this account.

        Uses EC2 describe_regions with AllRegions=False to only get
        regions that are enabled (default + manually opted-in).
        """
        if self._cached_enabled_regions:
            return self._cached_enabled_regions

        try:
            client_kwargs = {}
            if self.credentials:
                # SEC-06: Defensive extraction with validation
                ak = self.credentials.get("AccessKeyId")
                sk = self.credentials.get("SecretAccessKey")
                st = self.credentials.get("SessionToken")
                
                if not ak or not sk:
                    logger.warning("invalid_aws_credentials_keys", 
                                   has_ak=bool(ak), has_sk=bool(sk))
                    return self._get_fallback_regions()
                    
                client_kwargs = {
                    "aws_access_key_id": ak,
                    "aws_secret_access_key": sk,
                    "aws_session_token": st,
                }

            async with self.session.client("ec2", region_name="us-east-1", **client_kwargs) as ec2:
                response = await ec2.describe_regions(AllRegions=False)
                regions = [r["RegionName"] for r in response.get("Regions", [])]

                logger.info("regions_discovered", count=len(regions), source="ec2_describe_regions")
                self._cached_enabled_regions = regions
                return regions

        except ClientError as e:
            logger.error("region_discovery_failed", error=str(e))
            # Fallback to common regions if discovery fails
            return self._get_fallback_regions()

    async def get_hot_regions(self, days: int = 30) -> List[str]:
        """
        Get regions with recent cost activity (last N days).

        Uses Cost Explorer GetDimensionValues to find regions
        with >$0 spend. This optimizes scanning by skipping empty regions.
        """
        if self._cached_hot_regions:
            return self._cached_hot_regions

        try:
            client_kwargs = {}
            if self.credentials:
                # SEC-06: Defensive extraction with validation
                ak = self.credentials.get("AccessKeyId")
                sk = self.credentials.get("SecretAccessKey")
                st = self.credentials.get("SessionToken")
                
                if not ak or not sk:
                    logger.warning("invalid_aws_credentials_keys_hot", 
                                   has_ak=bool(ak), has_sk=bool(sk))
                    return await self.get_enabled_regions()
                    
                client_kwargs = {
                    "aws_access_key_id": ak,
                    "aws_secret_access_key": sk,
                    "aws_session_token": st,
                }

            end_date = date.today()
            start_date = end_date - timedelta(days=days)

            async with self.session.client("ce", region_name="us-east-1", **client_kwargs) as ce:
                response = await ce.get_dimension_values(
                    TimePeriod={
                        "Start": start_date.isoformat(),
                        "End": end_date.isoformat()
                    },
                    Dimension="REGION",
                    Context="COST_AND_USAGE"
                )

                regions = [dv["Value"] for dv in response.get("DimensionValues", [])]

                logger.info("hot_regions_discovered",
                           count=len(regions),
                           days=days,
                           source="cost_explorer")

                self._cached_hot_regions = regions
                return regions

        except ClientError as e:
            logger.warning("hot_region_discovery_failed", error=str(e))
            # Fall back to enabled regions
            return await self.get_enabled_regions()

    def _get_fallback_regions(self) -> List[str]:
        """Fallback region list when discovery fails."""
        return [
            "us-east-1",
            "us-west-2",
            "eu-west-1",
            "eu-central-1",
            "ap-southeast-1",
            "ap-northeast-1"
        ]

    def clear_cache(self) -> None:
        """Clear cached regions (useful for testing or forced refresh)."""
        self._cached_enabled_regions = []
        self._cached_hot_regions = []
