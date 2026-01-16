"""
Virtual Tagging Service - Gap #3

Uses LLMs to infer team and service ownership for cloud resources 
that are missing standard 'Team' or 'Service' tags.
"""

from typing import List, Dict, Any, Optional
from decimal import Decimal
import structlog
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel

logger = structlog.get_logger()

TAGGING_SYSTEM_PROMPT = """You are a cloud infrastructure tagging expert.
TASK:
Infer the most likely 'Team' and 'Service' ownership for the provided cloud cost records based on:
- Resource names
- Usage types
- Service type (EC2, RDS, etc.)
- Region

OUTPUT FORMAT (JSON ONLY):
{{
  "inferred_team": "Team Name",
  "inferred_service": "Service Name",
  "confidence_score": 0.0-1.0,
  "rationale": "Why you think so"
}}
"""

class VirtualTaggingService:
    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", TAGGING_SYSTEM_PROMPT),
            ("user", "Infer ownership for this resource:\n{resource_context}")
        ])

    async def infer_tags(self, resource_context: Dict[str, Any]) -> Dict[str, Any]:
        """Infers ownership for a single resource context."""
        try:
            chain = self.prompt | self.llm
            response = await chain.ainvoke({"resource_context": str(resource_context)})
            
            # Simple clean and parse
            content = response.content.strip()
            if content.startswith("```json"):
                content = content[7:-3].strip()
            
            import json
            return json.loads(content)
        except Exception as e:
            logger.error("virtual_tagging_failed", error=str(e))
            return {
                "inferred_team": "Unknown",
                "inferred_service": "Unknown",
                "confidence_score": 0.0,
                "rationale": str(e)
            }

    async def tag_records(self, records: List[Any]) -> List[Dict[str, Any]]:
        """Tags a batch of records."""
        # For MVP we might only tag unique resources to save tokens
        unique_resources = {}
        for r in records:
            key = f"{r.service}:{r.usage_type}:{r.region}"
            if key not in unique_resources:
                unique_resources[key] = {
                    "service": r.service,
                    "usage_type": r.usage_type,
                    "region": r.region
                }
        
        results = {}
        for key, context in unique_resources.items():
            results[key] = await self.infer_tags(context)
            
        return results
