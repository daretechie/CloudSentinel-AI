from datetime import date
from decimal import Decimal
from typing import List, Dict, Any, Optional
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cloud import CostRecord, CloudAccount
from app.schemas.costs import CloudUsageSummary, CostRecord as SchemaCostRecord

class CostAggregator:
    """Centralizes cost aggregation logic for the platform."""
    
    @staticmethod
    async def get_summary(
        db: AsyncSession,
        tenant_id: UUID,
        start_date: date,
        end_date: date,
        provider: Optional[str] = None
    ) -> CloudUsageSummary:
        """Fetches and aggregates cost records for a tenant."""
        stmt = (
            select(CostRecord)
            .where(
                CostRecord.tenant_id == tenant_id,
                CostRecord.timestamp >= start_date,
                CostRecord.timestamp <= end_date
            )
        )
        
        if provider:
            stmt = stmt.join(CloudAccount).where(CloudAccount.provider == provider.lower())
            
        result = await db.execute(stmt)
        records = result.scalars().all()
        
        # Aggregate logic (DRY)
        total_cost = Decimal("0.00")
        by_service = {}
        schema_records = []
        
        for r in records:
            total_cost += r.cost_usd
            by_service[r.service] = by_service.get(r.service, Decimal(0)) + r.cost_usd
            schema_records.append(SchemaCostRecord(
                date=r.timestamp,
                amount=r.cost_usd,
                service=r.service,
                region=r.region
            ))
            
        return CloudUsageSummary(
            tenant_id=str(tenant_id),
            provider=provider or "multi",
            start_date=start_date,
            end_date=end_date,
            total_cost=total_cost,
            records=schema_records,
            by_service=by_service
        )
    
    @staticmethod
    async def get_basic_breakdown(
        db: AsyncSession,
        tenant_id: UUID,
        start_date: date,
        end_date: date,
        provider: Optional[str] = None
    ) -> Dict[str, Any]:
        """Provides a simplified breakdown for the API."""
        stmt = (
            select(
                CostRecord.service,
                func.sum(CostRecord.cost_usd).label("total_cost"),
                func.sum(CostRecord.carbon_kg).label("total_carbon")
            )
            .where(
                CostRecord.tenant_id == tenant_id,
                CostRecord.recorded_at >= start_date,
                CostRecord.recorded_at <= end_date
            )
            .group_by(CostRecord.service)
        )
        
        if provider:
            stmt = stmt.join(CloudAccount, CostRecord.account_id == CloudAccount.id).where(
                CloudAccount.provider == provider.lower()
            )
            
        result = await db.execute(stmt)
        rows = result.all()
        
        total_cost = Decimal("0.00")
        total_carbon = Decimal("0.00")
        breakdown = []
        
        for row in rows:
            c = row.total_cost or Decimal(0)
            target_carbon = row.total_carbon or Decimal(0)
            total_cost += c
            total_carbon += target_carbon
            breakdown.append({
                "service": row.service,
                "cost": float(c),
                "carbon_kg": float(target_carbon)
            })
            
        return {
            "total_cost": float(total_cost),
            "total_carbon_kg": float(total_carbon),
            "breakdown": breakdown
        }
