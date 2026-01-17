from typing import Dict, Any, Optional
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
from app.services.llm.guardrails import LLMGuardrails, FinOpsAnalysisResult
from app.services.analysis.forecaster import SymbolicForecaster
from opentelemetry import trace
tracer = trace.get_tracer(__name__)
logger = structlog.get_logger()

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from app.core.exceptions import AIAnalysisError

# System prompts are now managed in prompts.yaml

class FinOpsAnalyzer:
    """
    The 'Brain' of Valdrix.

    This class wraps a LangChain ChatModel and orchestrates the analysis of cost data.
    It uses a specialized System Prompt to enforce strict JSON output for programmatic use.
    """
    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        
        # Load prompt from registry (Phase 21: Audit Hardening)
        import yaml
        import os
        prompt_path = os.path.join(os.path.dirname(__file__), "prompts.yaml")
        try:
            with open(prompt_path, "r") as f:
                registry = yaml.safe_load(f)
                system_prompt = registry["finops_analysis"]["system"]
        except Exception as e:
            logger.error("failed_to_load_prompts_yaml", error=str(e))
            # Fallback to a minimal prompt if registry fails
            system_prompt = "You are a FinOps expert. Analyze the cost data and return JSON."
            
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
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
        usage_summary: "CloudUsageSummary",
        tenant_id: Optional[UUID] = None,
        db: Optional[AsyncSession] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Takes normalized cloud usage data and returns AI-generated insights.
        
        This method handles:
        1. Cache and Delta Analysis checks.
        2. LLM client setup and budget verification.
        3. LangChain orchestration (Prompt -> LLM -> Output).
        4. Usage tracking and result processing.
        
        Args:
            usage_summary: The aggregated cost data to analyze.
            tenant_id: Tenant UUID for usage tracking and budget checks.
            db: Database session for persistence.
            provider: Optional provider override.
            model: Optional model override.
            force_refresh: bypass cache if True.
            
        Returns:
            A dictionary containing AI insights, recommendations, and anomalies.
            
        Raises:
            AIAnalysisError: If the LLM invocation or result processing fails.
            BudgetExceededError: If the tenant's LLM budget is exceeded.
        """
        from app.schemas.costs import CloudUsageSummary
        from app.core.exceptions import AIAnalysisError

        with tracer.start_as_current_span("analyze_costs") as span:
            span.set_attribute("tenant_id", str(tenant_id) if tenant_id else "anonymous")
            
            # 1. Cache & Delta Logic
            cached_analysis, is_delta = await self._check_cache_and_delta(
                tenant_id, force_refresh, usage_summary
            )
            if cached_analysis and not is_delta:
                return cached_analysis

            logger.info("starting_analysis", 
                        tenant_id=str(tenant_id), 
                        data_points=len(usage_summary.records),
                        mode="delta" if is_delta else "full",
                        cache_miss=not cached_analysis)

            # 2. Client & Usage Setup
            usage_tracker, effective_provider, effective_model, byok_key = \
                await self._setup_client_and_usage(tenant_id, db, provider, model)

            # 3. Prepare Data & Invoke LLM
            response_content, response_metadata = await self._invoke_llm(
                usage_summary, effective_provider, effective_model, byok_key
            )

            # 4. Track Usage
            await self._track_usage(
                usage_tracker, tenant_id, effective_provider, effective_model, 
                response_metadata, byok_key
            )

            # 5. Post-Process & Alert
            return await self._process_analysis_results(
                response_content, tenant_id, usage_summary
            )

    async def _check_cache_and_delta(
        self, tenant_id: Optional[UUID], force_refresh: bool, usage_summary: Any
    ) -> tuple[Optional[Dict], bool]:
        """Checks cache and determines if delta analysis should be performed."""
        if not tenant_id:
            return None, False

        cache = get_cache_service()
        cached_analysis = await cache.get_analysis(tenant_id) if not force_refresh else None
        
        if cached_analysis and not get_settings().ENABLE_DELTA_ANALYSIS:
            logger.info("analysis_cache_hit_full", tenant_id=str(tenant_id))
            return cached_analysis, False

        is_delta = False
        if cached_analysis and get_settings().ENABLE_DELTA_ANALYSIS:
            is_delta = True
            logger.info("analysis_delta_mode_enabled", tenant_id=str(tenant_id))
            from datetime import date, timedelta
            settings = get_settings()
            delta_cutoff = date.today() - timedelta(days=settings.DELTA_ANALYSIS_DAYS)
            
            original_records = usage_summary.records
            usage_summary.records = [r for r in original_records if r.date >= delta_cutoff]
            
            if not usage_summary.records:
                logger.info("analysis_delta_no_new_data", tenant_id=str(tenant_id))
                return cached_analysis, True # Return cache but mark as delta-handled

        return cached_analysis, is_delta

    async def _setup_client_and_usage(
        self, tenant_id: Optional[UUID], db: Optional[AsyncSession], 
        provider: Optional[str], model: Optional[str]
    ) -> tuple[Optional[UsageTracker], str, str, Optional[str]]:
        """Handles budget checks and determines the effective LLM provider/model."""
        usage_tracker = None
        byok_key = None
        effective_provider = provider
        effective_model = model

        if tenant_id and db:
            usage_tracker = UsageTracker(db)
            await usage_tracker.check_budget(tenant_id)

            from app.models.llm import LLMBudget
            result = await db.execute(select(LLMBudget).where(LLMBudget.tenant_id == tenant_id))
            budget = result.scalar_one_or_none()
            if budget:
                effective_provider = provider or budget.preferred_provider
                effective_model = model or budget.preferred_model
                keys = {
                    "openai": budget.openai_api_key,
                    "claude": budget.claude_api_key,
                    "anthropic": budget.claude_api_key,
                    "google": budget.google_api_key,
                    "groq": budget.groq_api_key
                }
                byok_key = keys.get(effective_provider)

        effective_provider = effective_provider or get_settings().LLM_PROVIDER
        effective_model = effective_model or model or "llama-3.3-70b-versatile"
        
        return usage_tracker, effective_provider, effective_model, byok_key

    async def _invoke_llm(
        self, usage_summary: Any, provider: str, model: str, byok_key: Optional[str]
    ) -> tuple[str, Dict]:
        """Orchestrates the LangChain invocation."""
        sanitized_data = await LLMGuardrails.sanitize_input(usage_summary.model_dump())
        
        with tracer.start_as_current_span("symbolic_forecast"):
            symbolic_forecast = SymbolicForecaster.forecast(usage_summary.records)
        sanitized_data["symbolic_forecast"] = symbolic_forecast
        
        formatted_data = json.dumps(sanitized_data, default=str)

        current_llm = self.llm
        if provider != get_settings().LLM_PROVIDER or byok_key:
            from app.services.llm.factory import LLMFactory
            current_llm = LLMFactory.create(provider, api_key=byok_key)

        chain = self.prompt | current_llm

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=4, max=10),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        )
        async def _invoke_with_retry():
            logger.info("invoking_llm", provider=provider, model=model)
            response = await chain.ainvoke({"cost_data": formatted_data})
            return response.content, getattr(response, "response_metadata", {})

        with tracer.start_as_current_span("llm_invocation") as span:
            span.set_attribute("llm.provider", provider)
            span.set_attribute("llm.model", model)
            try:
                return await _invoke_with_retry()
            except Exception as e:
                logger.error("llm_invocation_failed", provider=provider, error=str(e))
                from app.core.exceptions import AIAnalysisError
                raise AIAnalysisError(f"Failed to invoke LLM ({provider}): {str(e)}")

    async def _track_usage(
        self, usage_tracker: Optional[UsageTracker], tenant_id: Optional[UUID],
        provider: str, model: str, metadata: Dict, byok_key: Optional[str]
    ):
        """Records LLM usage metrics."""
        if not (tenant_id and usage_tracker):
            return

        try:
            token_usage = metadata.get("token_usage", {})
            await usage_tracker.record(
                tenant_id=tenant_id,
                provider=provider,
                model=model,
                input_tokens=token_usage.get("prompt_tokens", 0),
                output_tokens=token_usage.get("completion_tokens", 0),
                is_byok=byok_key is not None,
                request_type="cost_analysis",
            )
        except Exception as e:
            logger.warning("llm_usage_tracking_failed", error=str(e))

    async def _process_analysis_results(
        self, content: str, tenant_id: Optional[UUID], usage_summary: Any
    ) -> Dict[str, Any]:
        """Validates output, handles alerts, and caches results."""
        cache = get_cache_service()
        
        try:
            # 1. Validate LLM Output
            validated = LLMGuardrails.validate_output(content, FinOpsAnalysisResult)
            llm_result = validated.model_dump()
            
            # 2. Check and Alert for Anomaly
            await self._check_and_alert_anomalies(llm_result)
        except Exception as e:
            logger.warning("llm_validation_failed", error=str(e))
            # Fallback: try raw parsing if validation fails but it's still JSON
            try:
                llm_result = json.loads(self._strip_markdown(content))
            except json.JSONDecodeError as jde:
                logger.error("llm_fallback_json_parse_failed", error=str(jde), content_snippet=content[:100])
                llm_result = {"error": "AI analysis format invalid", "raw_content": content}
            except Exception as ex:
                logger.error("llm_fallback_failed_unexpectedly", error=str(ex))
                llm_result = {"error": "AI analysis processing failed", "raw_content": content}

        # 3. Combine with Symbolic Forecast (Neuro-Symbolic Bridge)
        symbolic_forecast = SymbolicForecaster.forecast(usage_summary.records)
        
        final_result = {
            "insights": llm_result.get("insights", []),
            "recommendations": llm_result.get("recommendations", []),
            "anomalies": llm_result.get("anomalies", []),
            "forecast": llm_result.get("forecast", {}),
            "symbolic_forecast": symbolic_forecast,
            "llm_raw": llm_result # Keep for debugging
        }
        
        # 4. Cache the combined result (24h TTL)
        if tenant_id:
            await cache.set_analysis(tenant_id, final_result)
            logger.info("analysis_cached", tenant_id=str(tenant_id))
        
        return final_result

    async def _check_and_alert_anomalies(self, result: Dict):
        """Sends Slack alerts if high-severity anomalies are found."""
        anomalies = result.get("anomalies", [])
        if not anomalies:
            return

        settings = get_settings()
        if settings.SLACK_BOT_TOKEN and settings.SLACK_CHANNEL_ID:
            slack = SlackService(settings.SLACK_BOT_TOKEN, settings.SLACK_CHANNEL_ID)
            top = anomalies[0]
            await slack.send_alert(
                title=f"Cost Anomaly Detected: {top['resource']}",
                message=f"*Issue:* {top['issue']}\n*Impact:* {top['cost_impact']}\n*Severity:* {top['severity']}",
                severity="critical" if top['severity'] == "high" else "warning"
            )
