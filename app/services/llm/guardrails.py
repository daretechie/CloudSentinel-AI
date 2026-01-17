import re
import json
from typing import Dict, Any, List, Type, TypeVar
from pydantic import BaseModel, Field, ValidationError
import structlog

logger = structlog.get_logger()

T = TypeVar("T", bound=BaseModel)

class LLMGuardrails:
    """
    Security guardrails for LLM interactions.
    
    Provides:
    1. Input sanitization (blocking prompt injection patterns)
    2. Structured output validation (ensuring JSON matches schema)
    """

    # Patterns commonly used in prompt injection
    INJECTION_PATTERNS = [
        r"ignore previous instructions",
        r"system prompt",
        r"output only",
        r"you are now",
        r"instead of",
        r"forget what you",
        r"<script>",
        r"javascript:",
    ]

    @classmethod
    async def sanitize_input(cls, data: Any, db: Any = None, tenant_id: Any = None) -> Any:
        """
        Recursively sanitizes input data to strip prompt injection attempts.
        """
        if isinstance(data, str):
            import unicodedata
            # 1. Normalize Unicode (handle homoglyph attacks)
            normalized = unicodedata.normalize('NFKC', data)
            
            # 2. Collapse whitespace to prevent "i g n o r e" bypass
            collapsed = re.sub(r'\s+', '', normalized).lower()
            
            # Check for pattern matches in collapsed string
            for pattern in cls.INJECTION_PATTERNS:
                # Remove spaces from pattern to match collapsed input
                clean_pattern = re.sub(r'\s+', '', pattern).lower()
                if clean_pattern in collapsed:
                    logger.warning("prompt_injection_obfuscated_form_detected", pattern=pattern)
                    return "[REDACTED]"
            
            # 3. ADVANCED: Adversarial Arbiter (Phase 18)
            # If the string is long or contains suspicious markers, we use a secondary 
            # arbiter check (Neuro-Symbolic verification).
            if len(data) > 100 or any(x in data.lower() for x in ["prompt", "ignore", "system"]):
                arbiter = AdversarialArbiter()
                if await arbiter.is_adversarial(data):
                    logger.critical("prompt_injection_blocked_by_arbiter", tenant_id=str(tenant_id))
                    return "[REDACTED]"

            # 4. Standard regex sanitization
            sanitized = data
            for pattern in cls.INJECTION_PATTERNS:
                sanitized = re.sub(pattern, "[REDACTED]", sanitized, flags=re.IGNORECASE)
            return sanitized
        
        elif isinstance(data, list):
            return [await cls.sanitize_input(item, db, tenant_id) for item in data]
        elif isinstance(data, dict):
            return {await cls.sanitize_input(k, db, tenant_id): await cls.sanitize_input(v, db, tenant_id) for k, v in data.items()}
        return False
    
    @classmethod
    def validate_output(cls, raw_content: str, schema_class: Type[T]) -> T:
        """
        Parses LLM output and validates it against a Pydantic schema.
        """
        try:
            # Strip markdown if present
            content = cls._strip_markdown(raw_content)
            data = json.loads(content)
            return schema_class(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error("llm_validation_failed", error=str(e), schema=schema_class.__name__)
            raise ValueError(f"LLM output failed validation for {schema_class.__name__}: {str(e)}") from e

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Removes markdown code block wrappers."""
        pattern = r'^```(?:json)?\s*\n?(.*?)\n?```$'
        match = re.match(pattern, text.strip(), re.DOTALL)
        if match:
            return match.group(1).strip()
        return text.strip()

class AdversarialArbiter:
    """
    High-fidelity secondary verification of prompts using heuristics 
    and (if necessary) a small, specialized LLM model.
    """
    async def is_adversarial(self, text: str) -> bool:
        # Heuristic: Ratio of special characters to letters
        # Attackers often obfuscate with symbols
        if not text:
            return False
            
        special_chars = len(re.sub(r'[a-zA-Z0-9\s]', '', text))
        if len(text) > 50 and (special_chars / len(text)) > 0.3:
            return True
            
        # Heuristic: Presence of "jailbreak" keywords not in INJECTION_PATTERNS
        jailbreak_keywords = ["dan", "jailbreak", "unfiltered", "developer mode", "do anything now"]
        if any(kw in text.lower() for kw in jailbreak_keywords):
            return True
            
        return False

# --- Pydantic Schemas for LLM Output ---

class CostAnomaly(BaseModel):
    resource: str
    issue: str
    cost_impact: str
    severity: str = Field(pattern="^(high|medium|low)$")

class ZombieResource(BaseModel):
    resource: str
    type: str
    current_cost: str
    utilization: str
    recommendation: str = Field(pattern="^(terminate|resize|investigate)$")

class FinOpsRecommendation(BaseModel):
    action: str
    resource: str
    estimated_savings: str
    priority: str = Field(pattern="^(high|medium|low)$")
    effort: str = Field(pattern="^(high|medium|low)$")
    confidence: str = Field(pattern="^(high|medium|low)$")

class FinOpsSummary(BaseModel):
    total_estimated_savings: str
    top_priority_action: str
    risk_level: str = Field(pattern="^(high|medium|low)$")

class FinOpsAnalysisResult(BaseModel):
    anomalies: List[CostAnomaly]
    zombie_resources: List[ZombieResource]
    recommendations: List[FinOpsRecommendation]
    summary: FinOpsSummary

# --- Zombie Specific Schemas ---

class ZombieDetail(BaseModel):
    resource_id: str
    resource_type: str
    provider: str = Field(pattern="^(aws|azure|gcp)$")
    explanation: str
    confidence: str = Field(pattern="^(high|medium|low)$")
    confidence_reason: str
    recommended_action: str
    monthly_cost: str
    risk_if_deleted: str = Field(pattern="^(high|medium|low)$")
    risk_explanation: str

class ZombieAnalysisResult(BaseModel):
    summary: str
    total_monthly_savings: str
    resources: List[ZombieDetail]
    general_recommendations: List[str]
