"""
AWS Cost & Usage Report (CUR) Adapter

Implements cost ingestion from CUR files in S3, which is the 2026 best practice
for enterprise-scale cost analysis:

Cost Comparison:
- Cost Explorer API: $0.01 per request (expensive at scale)
- CUR to S3: ~$0.01 per GB stored (much cheaper for large datasets)

Architecture:
1. Customer configures CUR export to their S3 bucket
2. Valdrix assumes role to read CUR files
3. CUR files are parsed (Parquet format recommended)
4. Results cached for fast subsequent queries
"""

import aioboto3
from datetime import date
from typing import List, Dict, Any
import structlog
from botocore.exceptions import ClientError

from app.services.adapters.base import CostAdapter

logger = structlog.get_logger()


class CURAdapter(CostAdapter):
    """
    Adapter for reading AWS Cost & Usage Reports from S3.

    This is more cost-effective than Cost Explorer API for:
    - Large enterprises with high API call volumes
    - Historical analysis (CUR has up to 3 years of data)
    - Detailed resource-level cost attribution

    Prerequisites:
    1. CUR export configured in customer's AWS account
    2. S3 bucket accessible via cross-account role
    3. Parquet format recommended for efficiency
    """

    def __init__(
        self,
        bucket_name: str,
        report_prefix: str,
        credentials: Dict[str, str],
        region: str = "us-east-1"
    ):
        self.bucket_name = bucket_name
        self.report_prefix = report_prefix
        self.credentials = credentials
        self.region = region
        self.session = aioboto3.Session()

    async def get_daily_costs(
        self,
        start_date: date,
        end_date: date,
        usage_only: bool = False,
        group_by_service: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Fetch daily costs from CUR files in S3.

        Note: This is a scaffold implementation. Full implementation requires:
        1. CUR manifest discovery
        2. Parquet file parsing (pyarrow)
        3. Date filtering and aggregation
        """
        try:
            # Step 1: List CUR files for the date range
            cur_files = await self._list_cur_files(start_date, end_date)

            if not cur_files:
                logger.warning("no_cur_files_found",
                             bucket=self.bucket_name,
                             prefix=self.report_prefix,
                             start=start_date.isoformat(),
                             end=end_date.isoformat())
                return []

            # Step 2: Parse and aggregate (scaffold)
            # TODO: Implement full Parquet parsing with pyarrow
            logger.info("cur_files_found",
                       count=len(cur_files),
                       bucket=self.bucket_name)

            # Placeholder: Return empty for now, integrate with pyarrow later
            return await self._parse_cur_files(cur_files, start_date, end_date, group_by_service)

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            logger.error("cur_fetch_failed", error=str(e), code=error_code)
            return [{"Error": str(e), "Code": error_code}]

    async def _list_cur_files(
        self,
        start_date: date,
        end_date: date
    ) -> List[str]:
        """List CUR Parquet files in S3 for the date range."""
        files = []

        async with self.session.client(
            "s3",
            region_name=self.region,
            aws_access_key_id=self.credentials.get("AccessKeyId"),
            aws_secret_access_key=self.credentials.get("SecretAccessKey"),
            aws_session_token=self.credentials.get("SessionToken"),
        ) as s3:
            try:
                # CUR files are organized by date: prefix/year/month/
                # We need to scan all months in the range
                current = start_date.replace(day=1)
                while current <= end_date:
                    prefix = f"{self.report_prefix}/{current.year}/{current.month:02d}/"

                    paginator = s3.get_paginator("list_objects_v2")
                    async for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                        for obj in page.get("Contents", []):
                            key = obj["Key"]
                            if key.endswith(".parquet"):
                                files.append(key)

                    # Move to next month
                    if current.month == 12:
                        current = current.replace(year=current.year + 1, month=1)
                    else:
                        current = current.replace(month=current.month + 1)

            except ClientError as e:
                logger.error("s3_list_failed", bucket=self.bucket_name, error=str(e))
                raise

        return files

    async def _parse_cur_files(
        self,
        files: List[str],
        start_date: date,
        end_date: date,
        group_by_service: bool
    ) -> List[Dict[str, Any]]:
        """
        Parse CUR Parquet files and aggregate costs.

        This is a scaffold - full implementation requires pyarrow.

        CUR Parquet schema includes columns like:
        - line_item_usage_start_date
        - line_item_blended_cost
        - line_item_product_code (service name)
        - line_item_resource_id
        """
        # TODO: Implement with pyarrow
        # Example pseudocode:
        # import pyarrow.parquet as pq
        #
        # for file_key in files:
        #     # Download file from S3
        #     # Read with pyarrow
        #     table = pq.read_table(file_bytes)
        #
        #     # Filter by date range
        #     # Group by date and optionally service
        #     # Aggregate costs

        logger.info("cur_parsing_not_implemented",
                   msg="CUR parsing requires pyarrow - returning empty",
                   files=len(files))

        return []

    async def get_gross_usage(
        self,
        start_date: date,
        end_date: date
    ) -> List[Dict[str, Any]]:
        """Get usage-only costs grouped by service."""
        return await self.get_daily_costs(
            start_date,
            end_date,
            usage_only=True,
            group_by_service=True
        )

    async def get_resource_usage(self, service_name: str) -> List[Dict[str, Any]]:
        """
        Get resource-level costs for a specific service.

        CUR provides line_item_resource_id which enables this,
        unlike Cost Explorer which only goes to service level.
        """
        # TODO: Implement resource-level cost attribution
        return []


class CURConfig:
    """
    Configuration for CUR-based cost ingestion.

    Stored per-tenant to support different CUR locations.
    """

    def __init__(
        self,
        bucket_name: str,
        report_prefix: str,
        report_name: str,
        format: str = "Parquet"  # Parquet or CSV
    ):
        self.bucket_name = bucket_name
        self.report_prefix = report_prefix
        self.report_name = report_name
        self.format = format

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CURConfig":
        return cls(
            bucket_name=data["bucket_name"],
            report_prefix=data["report_prefix"],
            report_name=data["report_name"],
            format=data.get("format", "Parquet")
        )
