from typing import List, Dict, Any, Optional
import json
import re
import structlog
from uuid import UUID

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.llm.usage_tracker import UsageTracker
from app.services.notifications import SlackService
from app.services.cache import get_cache_service

logger = structlog.get_logger()

# The "System Prompt" - defines the AI's personality and task
FINOPS_SYSTEM_PROMPT = """You are a FinOps cost analysis expert specializing in cloud infrastructure optimization.
TASK:
Analyze the provided cloud cost data and identify cost optimization opportunities.

INPUT DATA FORMAT:
- Resource usage metrics (CPU, memory, network)
- Cost trends over the past 30 days
- Resource metadata (type, region, tags)

ANALYSIS CRITERIA:
1. Anomalies: Cost changes greater than 30% week-over-week or unexpected spending patterns
2. Zombie Resources: Resources with less than 5% utilization for 7 or more consecutive days
3. Optimizations: Right-sizing opportunities with greater than 20% potential savings, reserved instance candidates, and idle resources

OUTPUT FORMAT (STRICT JSON ONLY):
{{
  "anomalies": [
    {{
      "resource": "resource-id or name",
      "issue": "description of anomaly",
      "cost_impact": "$XX/month",
      "severity": "high|medium|low"
    }}
  ],
  "zombie_resources": [
    {{
      "resource": "resource-id",
      "type": "EC2|RDS|ELB|Other",
      "current_cost": "$XX/month",
      "utilization": "X%",
      "recommendation": "terminate|resize|investigate"
    }}
  ],
  "recommendations": [
    {{
      "action": "specific action to take",
      "resource": "affected resource(s)",
      "estimated_savings": "$XX/month",
      "priority": "high|medium|low",
      "effort": "low|medium|high",
      "confidence": "high|medium|low"
    }}
  ],
  "summary": {{
    "total_estimated_savings": "$XXX/month",
    "top_priority_action": "most impactful recommendation",
    "risk_level": "low|medium|high"
  }}
}}

RULES:
- Return valid JSON only (no markdown, no explanations)
- Use exact enum values as specified
- Base all conclusions strictly on the provided data
- If no issues are found, return empty arrays and set total_estimated_savings to "$0/month"
- Prioritize recommendations by ROI (estimated savings versus implementation effort)
"""

class FinOpsAnalyzer:
    """
    The 'Brain' of Valdrix.

    This class wraps a LangChain ChatModel and orchestrates the analysis of cost data.
    It uses a specialized System Prompt to enforce strict JSON output for programmatic use.
    """
    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", FINOPS_SYSTEM_PROMPT),
            ("user", "Analyze this cloud cost data:\n{cost_data}")
        ])

    def _strip_markdown(self, text: str) -> str:
      """
      Removes markdown code block wrappers from LLM responses.
      LLMs often ignore 'no markdown' instructions.
      """
      # Pattern matches ```json ... ``` or just ``` ... ```
      pattern = r'^```(?:json)?\s*\n?(.*?)\n?```$'
      match = re.match(pattern, text.strip(), re.DOTALL)
      if match:
        return match.group(1).strip()
      return text.strip()

    async def analyze(
    self,
    cost_data: List[Dict[str, Any]],
    tenant_id: Optional[UUID] = None,
    db: Optional[AsyncSession] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    force_refresh: bool = False,) -> str:
        """
        Takes raw cost data and returns AI-generated insights.

        The process:
        1. Check cache for recent analysis (if tenant_id provided)
        2. Formats the raw list of dictionaries into a string.
        3. Injects it into the prompt template.
        4. Invokes the LLM to process the data against the System Prompt.
        5. Strips any markdown formatting from the response to ensure valid JSON.
        6. Caches the result for 24 hours

        Args:
            cost_data: List of daily cost records from the adapter.
            force_refresh: Skip cache and force new LLM analysis.

        Returns:
            str: A raw JSON string containing the analysis.
        """
        cache = get_cache_service()
        
        # Check cache first (unless force_refresh)
        if tenant_id and not force_refresh:
            cached = await cache.get_analysis(tenant_id)
            if cached:
                logger.info("analysis_cache_hit", tenant_id=str(tenant_id))
                return json.dumps(cached)
        
        logger.info("starting_analysis", data_points=len(cost_data), cache_miss=True)

        # Format cost data as JSON string for the prompt (better than str() for LLMs)
        formatted_data = json.dumps(cost_data, default=str)

        # Determine provider and model
        effective_provider = provider
        effective_model = model

        if tenant_id and db and (not effective_provider or not effective_model):
            from app.models.llm import LLMBudget
            result = await db.execute(select(LLMBudget).where(LLMBudget.tenant_id == tenant_id))
            budget = result.scalar_one_or_none()
            if budget:
                effective_provider = effective_provider or budget.preferred_provider
                effective_model = effective_model or budget.preferred_model

        # Fallbacks if still none
        effective_provider = effective_provider or get_settings().LLM_PROVIDER
        effective_model = effective_model or "llama-3.3-70b-versatile"

        # BYOK Check: Fetch tenant-specific API key if available
        byok_key = None
        if tenant_id and db:
            from app.models.llm import LLMBudget
            result = await db.execute(select(LLMBudget).where(LLMBudget.tenant_id == tenant_id))
            budget = result.scalar_one_or_none()
            if budget:
                if effective_provider == "openai":
                    byok_key = budget.openai_api_key
                elif effective_provider in ["claude", "anthropic"]:
                    byok_key = budget.claude_api_key
                elif effective_provider == "google":
                    byok_key = budget.google_api_key
                elif effective_provider == "groq":
                    byok_key = budget.groq_api_key

        # Build the chain: Prompt -> LLM
        # We need to ensure self.llm matches the effective_provider if they differ or if BYOK is used

        current_llm = self.llm
        if effective_provider != get_settings().LLM_PROVIDER or byok_key:
             from app.services.llm.factory import LLMFactory
             current_llm = LLMFactory.create(effective_provider, api_key=byok_key)

        chain = self.prompt | current_llm

        # Invoke the chain
        response = await chain.ainvoke({"cost_data": formatted_data})

        # Track LLM usage if tenant context provided
        if tenant_id and db:
            try:
                # Extract token usage from response metadata
                usage_metadata = response.response_metadata.get("token_usage", {})
                input_tokens = usage_metadata.get("prompt_tokens", 0)
                output_tokens = usage_metadata.get("completion_tokens", 0)

                # Record usage
                tracker = UsageTracker(db)
                await tracker.record(
                    tenant_id=tenant_id,
                    provider=effective_provider,
                    model=effective_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    is_byok=byok_key is not None,
                    request_type="cost_analysis",
                )
            except Exception as e:
                # Don't fail the analysis if tracking fails
                logger.warning("llm_usage_tracking_failed", error=str(e))

        logger.info("analysis_complete")

        # After analysis, check for anomalies and alert
        try:
            result = json.loads(self._strip_markdown(response.content))
            
            # Cache the result for future requests (24h TTL)
            if tenant_id:
                await cache.set_analysis(tenant_id, result)
                logger.info("analysis_cached", tenant_id=str(tenant_id))
            
            if result.get("anomalies") and len(result["anomalies"]) > 0:
                settings = get_settings()
                if settings.SLACK_BOT_TOKEN and settings.SLACK_CHANNEL_ID:
                    slack = SlackService(settings.SLACK_BOT_TOKEN, settings.SLACK_CHANNEL_ID)

                    top_anomaly = result["anomalies"][0]
                    await slack.send_alert(
                        title=f"Cost Anomaly Detected: {top_anomaly['resource']}",
                        message=f"*Issue:* {top_anomaly['issue']}\n*Impact:* {top_anomaly['cost_impact']}\n*Severity:* {top_anomaly['severity']}",
                        severity="critical" if top_anomaly['severity'] == "high" else "warning"
                    )
        except json.JSONDecodeError as e:
            logger.warning("llm_response_json_parse_failed", error=str(e))

        return self._strip_markdown(response.content)
