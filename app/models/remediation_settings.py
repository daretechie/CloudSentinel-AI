from uuid import uuid4
from sqlalchemy import Boolean, Numeric, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

class RemediationSettings(Base):
    """
    Per-tenant settings for Autonomous Remediation (ActiveOps).
    """
    __tablename__ = "remediation_settings"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4
    )
    
    tenant_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        unique=True,
        nullable=False
    )
    
    # Global Kill-Switch for Auto-Pilot
    auto_pilot_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Safety Thresholds
    min_confidence_threshold: Mapped[float] = mapped_column(Numeric(3, 2), default=0.95)
    
    # Relationship
    tenant = relationship("Tenant")

    def __repr__(self):
        return f"<RemediationSettings tenant={self.tenant_id} auto_pilot={self.auto_pilot_enabled}>"
