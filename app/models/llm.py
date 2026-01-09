"""
LLM Usage Tracking Model

This model stores every LLM API call for cost tracking and analytics.
Each record captures: who made the call (tenant), what model was used,
how many tokens were consumed, and the calculated cost.

Why this matters:
- Bill users accurately for AI usage (future pricing tiers)
- Optimize prompts (see which cost the most)
- Analytics dashboard (AI spend over time)
"""

from uuid import uuid4
from sqlalchemy import Column, String, Integer, Numeric, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class LLMUsage(Base):
    """
    Tracks individual LLM API calls for cost analytics.
    
    Example usage:
        usage = LLMUsage(
            tenant_id=current_user.tenant_id,
            provider="groq",
            model="llama-3.3-70b-versatile",
            input_tokens=1500,
            output_tokens=800,
            total_tokens=2300,
            cost_usd=0.0015,
            request_type="daily_analysis"
        )
        db.add(usage)
        await db.commit()
    """
    
    __tablename__ = "llm_usage"
    
    # Primary Key: UUID prevents enumeration attacks
    # default=uuid4 generates a new UUID if not provided
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Foreign Key: Links this record to a tenant
    # Every LLM call belongs to a tenant (multi-tenancy)
    # ondelete="CASCADE": If tenant is deleted, their usage records go too
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,  # Fast filtering by tenant
    )
    
    # Provider: Which company's API (openai, anthropic, groq)
    # Why separate from model: Same model can be on different providers
    provider = Column(String(50), nullable=False)
    
    # Model: Specific model used (gpt-4o, claude-3-sonnet, llama-3.3-70b)
    # Important for cost calculation (each model has different pricing)
    model = Column(String(100), nullable=False, index=True)
    
    # Token counts: The currency of LLM pricing
    # input_tokens: How many tokens in your prompt
    # output_tokens: How many tokens in the response
    # total_tokens: Convenience field (input + output)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    
    # Cost in USD: Calculated at time of call
    # Numeric(10,6): Up to $9999.999999 with 6 decimal precision
    # Why 6 decimals: Token costs are tiny fractions of cents
    cost_usd = Column(Numeric(10, 6), nullable=False, default=0)
    
    # Request Type: What was this LLM call for?
    # Examples: "daily_analysis", "chat", "anomaly_detection"
    # Useful for analytics: "80% of cost comes from daily_analysis"
    request_type = Column(String(50), nullable=True)
    
    # created_at is inherited from Base (automatic timestamp)
    # updated_at is inherited from Base (automatic on update)
    
    # Relationship: Access the tenant object
    # Use: usage.tenant.name
    tenant = relationship("Tenant", back_populates="llm_usage")
    
    def __repr__(self):
        """String representation for debugging."""
        return f"<LLMUsage {self.model} ${self.cost_usd:.6f}>"


class LLMBudget(Base):
    """
    Tracks monthly LLM usage budget per tenant.
    
    Enables:
    - Soft alerts: Notify when usage hits threshold (e.g., 80%)
    - Hard limits: Optionally block requests when budget exceeded
    - Cost control: Prevent surprise AI bills
    
    Example:
        budget = LLMBudget(
            tenant_id=tenant.id,
            monthly_limit_usd=Decimal("10.00"),
            alert_threshold_percent=80,
            hard_limit=False,  # Alert only, don't block
        )
    """
    
    __tablename__ = "llm_budgets"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Foreign Key: One budget per tenant
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # One budget per tenant
        index=True,
    )
    
    # Monthly limit in USD (e.g., $10.00)
    # Numeric(10,2): Up to $99,999,999.99
    monthly_limit_usd = Column(Numeric(10, 2), nullable=False, default=10.00)
    
    # Alert threshold percentage (e.g., 80 = alert at 80% usage)
    alert_threshold_percent = Column(Integer, nullable=False, default=80)
    
    # Hard limit: If True, block LLM requests when budget exceeded
    # If False, just alert but allow requests to continue
    hard_limit = Column(String(10), nullable=False, default="false")
    
    # Track if alert has been sent this month (avoid spam)
    alert_sent_at = Column(String(50), nullable=True)
    
    # Relationship
    tenant = relationship("Tenant", back_populates="llm_budget")
    
    def __repr__(self):
        return f"<LLMBudget ${self.monthly_limit_usd}/month>"