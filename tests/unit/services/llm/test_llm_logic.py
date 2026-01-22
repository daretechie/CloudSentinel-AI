"""
Tests for LLM Logic - Provider Selection and Smart Factory
"""
import pytest
from unittest.mock import MagicMock, patch
from app.services.llm.factory import LLMFactory, LLMProviderSelector, AnalysisComplexity


def test_estimate_tokens():
    """Test token estimation logic (4 chars per token)."""
    assert LLMProviderSelector.estimate_tokens("1234") == 1
    assert LLMProviderSelector.estimate_tokens("12345678") == 2
    assert LLMProviderSelector.estimate_tokens("") == 0


def test_classify_complexity():
    """Test complexity classification based on token counts."""
    assert LLMProviderSelector.classify_complexity(500) == AnalysisComplexity.SIMPLE
    assert LLMProviderSelector.classify_complexity(1500) == AnalysisComplexity.MEDIUM
    assert LLMProviderSelector.classify_complexity(5000) == AnalysisComplexity.COMPLEX


def test_select_provider_byok_priority():
    """Test that BYOK provider always takes priority."""
    with patch("app.services.llm.factory.get_settings") as mock_settings:
        provider, complexity = LLMProviderSelector.select_provider(
            "short text", tenant_byok_provider="openai"
        )
        assert provider == "openai"
        # BYOK forced to MEDIUM by default in implementation
        assert complexity == AnalysisComplexity.MEDIUM


def test_select_provider_waterfall_simple():
    """Test waterfall selection for SIMPLE complexity (Groq preferred)."""
    with patch("app.services.llm.factory.get_settings") as mock_settings:
        mock_settings.return_value.GROQ_API_KEY = "sk-groq-valid-key-long-enough"
        
        provider, complexity = LLMProviderSelector.select_provider("A" * 100) # ~25 tokens
        assert complexity == AnalysisComplexity.SIMPLE
        assert provider == "groq"


def test_select_provider_waterfall_medium():
    """Test waterfall selection for MEDIUM complexity (Google preferred)."""
    with patch("app.services.llm.factory.get_settings") as mock_settings:
        mock_settings.return_value.GROQ_API_KEY = "sk-groq-valid-key-long-enough"
        mock_settings.return_value.GOOGLE_API_KEY = "google-valid-key-long-enough"
        
        provider, complexity = LLMProviderSelector.select_provider("A" * 6000) # ~1500 tokens
        assert complexity == AnalysisComplexity.MEDIUM
        assert provider == "google"


def test_select_provider_waterfall_complex():
    """Test waterfall selection for COMPLEX complexity (OpenAI preferred)."""
    with patch("app.services.llm.factory.get_settings") as mock_settings:
        mock_settings.return_value.OPENAI_API_KEY = "sk-openai-valid-key-long-enough"
        
        provider, complexity = LLMProviderSelector.select_provider("A" * 20000) # ~5000 tokens
        assert complexity == AnalysisComplexity.COMPLEX
        assert provider == "openai"


def test_estimate_cost_groq():
    """Test cost estimation for Groq (free)."""
    cost = LLMProviderSelector.estimate_cost("groq", 1000, 500)
    assert cost == 0.0


def test_estimate_cost_paid_provider():
    """Test cost estimation for paid providers."""
    # OpenAI costs from PROVIDER_COSTS: 0.00015 input, 0.0006 output per 1K
    cost = LLMProviderSelector.estimate_cost("openai", 1000, 1000)
    expected = 0.00015 + 0.0006
    assert abs(cost - expected) < 1e-6


def test_llm_factory_validate_api_key_valid():
    """Test API key validation with valid key."""
    # Should not raise
    LLMFactory.validate_api_key("openai", "sk-proj-valid-key-at-least-twenty-chars")


def test_llm_factory_validate_api_key_missing():
    """Test API key validation failure with missing key."""
    with pytest.raises(ValueError, match="not configured"):
        LLMFactory.validate_api_key("openai", None)


def test_llm_factory_validate_api_key_placeholder():
    """Test API key validation failure with placeholder."""
    with pytest.raises(ValueError, match="placeholder"):
        LLMFactory.validate_api_key("openai", "sk-xxx-key")


def test_llm_factory_validate_api_key_too_short():
    """Test API key validation failure with too short key."""
    with pytest.raises(ValueError, match="too short"):
        LLMFactory.validate_api_key("openai", "sk-short")


@pytest.mark.asyncio
async def test_llm_factory_create_smart():
    """Test smart creation combining selection and instantiation."""
    with patch("app.services.llm.factory.LLMProviderSelector.select_provider") as mock_select:
        mock_select.return_value = ("groq", AnalysisComplexity.SIMPLE)
        
        with patch("app.services.llm.factory.LLMFactory.create") as mock_create:
            mock_create.return_value = MagicMock()
            
            llm, provider, complexity = LLMFactory.create_smart("input text")
            
            assert provider == "groq"
            assert complexity == AnalysisComplexity.SIMPLE
            mock_create.assert_called_with(provider="groq", api_key=None)

@pytest.mark.asyncio
async def test_llm_factory_create_google():
    """Test creating Google Gemini client."""
    with patch("app.services.llm.factory.ChatGoogleGenerativeAI") as mock_gemini:
        with patch("app.services.llm.factory.get_settings") as mock_settings:
            mock_settings.return_value.GOOGLE_API_KEY = "google-valid-key-long-enough"
            mock_settings.return_value.GOOGLE_MODEL = "gemini-flash"
            
            LLMFactory.create(provider="google")
            mock_gemini.assert_called_with(
                google_api_key="google-valid-key-long-enough",
                model="gemini-flash",
                temperature=0
            )

@pytest.mark.asyncio
async def test_llm_factory_create_groq():
    """Test creating Groq client."""
    with patch("app.services.llm.factory.ChatGroq") as mock_groq:
        with patch("app.services.llm.factory.get_settings") as mock_settings:
            mock_settings.return_value.GROQ_API_KEY = "groq-valid-key-long-enough"
            mock_settings.return_value.GROQ_MODEL = "llama-3"
            
            LLMFactory.create(provider="groq")
            mock_groq.assert_called_with(
                api_key="groq-valid-key-long-enough",
                model="llama-3",
                temperature=0
            )

def test_llm_factory_create_unsupported():
    """Test error when creating unsupported provider."""
    with pytest.raises(ValueError, match="Unsupported provider"):
        LLMFactory.create(provider="unknown-ai")
