"""
Cost Persistence Service - Phase 11: Scalability & Polish

Handles idempotent storage of normalized cost data into the database.
Supports both daily and hourly granularity.
"""

from typing import Any, Dict, AsyncIterable, List
from datetime import date, datetime, timedelta
from decimal import Decimal
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
import structlog
from app.models.cloud import CostRecord
from app.schemas.costs import CloudUsageSummary

logger = structlog.get_logger()

class CostPersistenceService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def save_summary(self, summary: CloudUsageSummary, account_id: str) -> dict:
        """
        Saves a CloudUsageSummary to the database.
        Uses PostgreSQL ON CONFLICT DO UPDATE for idempotency.
        """
        records_saved = 0
        total_processed = len(summary.records)
        
        # Batch size for database performance
        BATCH_SIZE = 500
        
        for i in range(0, total_processed, BATCH_SIZE):
            batch = summary.records[i : i + BATCH_SIZE]
            
            # Prepare values for bulk insert
            values = []
            for r in batch:
                values.append({
                    "tenant_id": summary.tenant_id,
                    "account_id": account_id,
                    "service": r.service or "Unknown",
                    "region": r.region or "Global",
                    "cost_usd": r.amount,
                    "amount_raw": r.amount_raw,
                    "currency": r.currency,
                    "recorded_at": r.date.date(), # Legacy date column
                    "timestamp": r.date,           # New hourly/timestamp column
                    "usage_type": r.usage_type
                })
            
            # PostgreSQL-specific Upsert logic (Atomic Ops)
            stmt = insert(CostRecord).values(values)
            stmt = stmt.on_conflict_do_update(
                constraint="uix_account_cost_granularity",
                set_={
                    "cost_usd": stmt.excluded.cost_usd,
                    "amount_raw": stmt.excluded.amount_raw,
                    "currency": stmt.excluded.currency
                }
            )
            await self.db.execute(stmt)
            records_saved += len(values)

        # Item 13: Explicitly commit at the end of a full summary save
        await self.db.commit()
        
        logger.info("cost_persistence_success", 
                    tenant_id=summary.tenant_id, 
                    account_id=account_id, 
                    records=records_saved)
        
        return {"records_saved": records_saved}

    async def save_records_stream(
        self, 
        records: AsyncIterable[Dict[str, Any]], 
        tenant_id: str, 
        account_id: str
    ) -> dict:
        """
        Consumes an async stream of cost records and saves them in batches.
        Prevents memory spikes for massive accounts.
        """
        records_saved = 0
        batch = []
        BATCH_SIZE = 500

        async for r in records:
            batch.append({
                "tenant_id": tenant_id,
                "account_id": account_id,
                "service": r.get("service") or "Unknown",
                "region": r.get("region") or "Global",
                "cost_usd": r.get("cost_usd"),
                "amount_raw": r.get("amount_raw"),
                "currency": r.get("currency"),
                "recorded_at": r["timestamp"].date(),
                "timestamp": r["timestamp"],
                "usage_type": r.get("usage_type", "Usage")
            })

            if len(batch) >= BATCH_SIZE:
                await self._bulk_upsert(batch)
                records_saved += len(batch)
                batch = []

        if batch:
            await self._bulk_upsert(batch)
            records_saved += len(batch)

        logger.info("cost_stream_persistence_success", 
                    tenant_id=tenant_id, 
                    account_id=account_id, 
                    records=records_saved)
        
        return {"records_saved": records_saved}

    async def _bulk_upsert(self, values: List[Dict[str, Any]]):
        """Helper for PostgreSQL ON CONFLICT DO UPDATE bulk insert."""
        stmt = insert(CostRecord).values(values)
        stmt = stmt.on_conflict_do_update(
            constraint="uix_account_cost_granularity",
            set_={
                "cost_usd": stmt.excluded.cost_usd,
                "amount_raw": stmt.excluded.amount_raw,
                "currency": stmt.excluded.currency
            }
        )
        await self.db.execute(stmt)

    async def clear_range(self, account_id: str, start_date: Any, end_date: Any):
        """Clears existing records to allow re-ingestion."""
        stmt = delete(CostRecord).where(
            CostRecord.account_id == account_id,
            CostRecord.timestamp >= start_date,
            CostRecord.timestamp <= end_date
        )
        await self.db.execute(stmt)

    async def cleanup_old_records(self, days_retention: int = 365) -> Dict[str, int]:
        """
        Deletes cost records older than the specified retention period in small batches.
        Optimized for space reclamation without long-running database locks.
        """
        from datetime import timezone
        cutoff_date = datetime.combine(
            date.today() - timedelta(days=days_retention), 
            datetime.min.time()
        ).replace(tzinfo=timezone.utc)
        total_deleted = 0
        batch_size = 5000 # Configurable batch size
        while True:
            # 1. Fetch a batch of IDs to delete
            stmt = select(CostRecord.id).where(CostRecord.timestamp < cutoff_date).limit(batch_size)
            result = await self.db.execute(stmt)
            ids = result.scalars().all()
            
            if not ids:
                break
                
            # 2. Delete this batch
            stmt = delete(CostRecord).where(CostRecord.id.in_(ids))
            await self.db.execute(stmt)
            
            total_deleted += len(ids)
            await self.db.commit() # Commit each batch to free locks and logs
        
        logger.info("cost_retention_cleanup_complete", cutoff_date=str(cutoff_date), total_deleted=total_deleted)
        return {"deleted_count": total_deleted}
