from fastapi import Depends
from app.core.config import get_settings
from app.services.llm.factory import LLMFactory
from app.services.llm.analyzer import FinOpsAnalyzer

def get_llm_provider() -> str:
    settings = get_settings()
    return settings.LLM_PROVIDER

def get_analyzer(provider: str = Depends(get_llm_provider)) -> FinOpsAnalyzer:
    llm = LLMFactory.create(provider)
    return FinOpsAnalyzer(llm)
