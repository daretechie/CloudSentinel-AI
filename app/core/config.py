from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from typing import Optional


class Settings(BaseSettings):
    """
    Main configuration for Valdrix AI.
    Uses Pydantic-Settings for environment variable parsing from .env.
    """
    APP_NAME: str = "Valdrix"
    VERSION: str = "0.1.0"
    DEBUG: bool = False
    API_URL: str = "http://localhost:8000"  # Base URL for OIDC and Magic Links
    OTEL_EXPORTER_OTLP_ENDPOINT: Optional[str] = None # Added for D5: Telemetry Sink
    OTEL_EXPORTER_OTLP_INSECURE: bool = False # SEC-07: Secure Tracing
    CSRF_SECRET_KEY: str = "change-me-in-production-csrf" # SEC-01: CSRF
    TESTING: bool = False

    @model_validator(mode='after')
    def validate_csrf_key_in_production(self) -> 'Settings':
        """Fail-closed: Prevent startup with default CSRF key in production."""
        if not self.TESTING and not self.DEBUG:
            if self.CSRF_SECRET_KEY == "change-me-in-production-csrf":
                raise ValueError(
                    "SECURITY ERROR: CSRF_SECRET_KEY must be changed from default in production! "
                    "Set CSRF_SECRET_KEY environment variable to a secure random value."
                )
        return self


    # AWS Credentials
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_DEFAULT_REGION: str = "us-east-1"
    
    # CloudFormation Template (Configurable for S3/GitHub)
    CLOUDFORMATION_TEMPLATE_URL: str = "https://raw.githubusercontent.com/Valdrix-AI/valdrix/main/cloudformation/valdrix-role.yaml"
    
    # Reload trigger: 2026-01-14

    # Security
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"]
    FRONTEND_URL: str = "http://localhost:5173"  # Used for billing callbacks
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o" # High performance for complex analysis

    # Claude/Anthropic Credentials
    CLAUDE_API_KEY: Optional[str] = None
    CLAUDE_MODEL: str = "claude-3-7-sonnet"
    ANTHROPIC_API_KEY: Optional[str] = None # Added for Phase 28 compatibility

    # Google Gemini Credentials
    GOOGLE_API_KEY: Optional[str] = None
    GOOGLE_MODEL: str = "gemini-2.0-flash"

    # Groq Credentials
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # LLM Provider
    LLM_PROVIDER: str = "groq" # Options: openai, claude, google, groq
    ENABLE_DELTA_ANALYSIS: bool = True # Innovation 1: Reduce token usage by 90%
    DELTA_ANALYSIS_DAYS: int = 3

    # Scheduler
    SCHEDULER_HOUR: int = 8
    SCHEDULER_MINUTE: int = 0

    # Admin API Key
    ADMIN_API_KEY: Optional[str] = None

    # Database
    DATABASE_URL: str # Required in prod
    DB_SSL_MODE: str = "require"  # Options: disable, require, verify-ca, verify-full
    DB_SSL_CA_CERT_PATH: Optional[str] = None  # Path to CA cert for verify-ca/verify-full modes
    DB_POOL_SIZE: int = 20  # Standard for Supabase/Neon free tiers
    DB_MAX_OVERFLOW: int = 10

    # Supabase Auth
    SUPABASE_URL: Optional[str] = None
    SUPABASE_JWT_SECRET: str # Required for auth middleware

    # Notifications
    SLACK_BOT_TOKEN: Optional[str] = None
    SLACK_CHANNEL_ID: Optional[str] = None

    # SMTP Email (for carbon alerts)
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: str = "alerts@valdrix.ai"

    # Encryption & Secret Rotation
    ENCRYPTION_KEY: Optional[str] = None
    PII_ENCRYPTION_KEY: Optional[str] = None
    API_KEY_ENCRYPTION_KEY: Optional[str] = None
    LEGACY_ENCRYPTION_KEYS: list[str] = []
    BLIND_INDEX_KEY: Optional[str] = None # SEC-06: Separation of keys
    
    # KDF Settings for password-to-key derivation (SEC-06)
    KDF_SALT: str = "valdrix-default-salt-2026"
    KDF_ITERATIONS: int = 100000


    # Cache (Redis for production, in-memory for dev)
    REDIS_URL: Optional[str] = None  # e.g., redis://localhost:6379
    
    # Upstash Redis (Serverless - Free tier: 10K commands/day)
    UPSTASH_REDIS_URL: Optional[str] = None  # e.g., https://xxx.upstash.io
    UPSTASH_REDIS_TOKEN: Optional[str] = None

    # Paystack Billing (Nigeria Support)
    PAYSTACK_SECRET_KEY: Optional[str] = None
    PAYSTACK_PUBLIC_KEY: Optional[str] = None
    EXCHANGERATE_API_KEY: Optional[str] = None # Added for dynamic currency
    # Monthly plans
    PAYSTACK_PLAN_STARTER: str = "PLN_starter_xxx"    # ₦41,250/mo ($29)
    PAYSTACK_PLAN_GROWTH: str = "PLN_growth_xxx"      # ₦112,350/mo ($79)
    PAYSTACK_PLAN_PRO: str = "PLN_pro_xxx"            # ₦283,000/mo ($199)
    PAYSTACK_PLAN_ENTERPRISE: str = "PLN_ent_xxx"     # Custom
    # Annual plans (17% discount - 2 months free)
    PAYSTACK_PLAN_STARTER_ANNUAL: Optional[str] = None
    PAYSTACK_PLAN_GROWTH_ANNUAL: Optional[str] = None
    PAYSTACK_PLAN_PRO_ANNUAL: Optional[str] = None
    PAYSTACK_PLAN_ENTERPRISE_ANNUAL: Optional[str] = None

    # Circuit Breaker Defaults
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 3
    CIRCUIT_BREAKER_RECOVERY_SECONDS: int = 300
    CIRCUIT_BREAKER_MAX_DAILY_SAVINGS: float = 1000.0

    # Scanner Settings
    ZOMBIE_PLUGIN_TIMEOUT_SECONDS: int = 30
    ZOMBIE_REGION_TIMEOUT_SECONDS: int = 120

    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True
    )

    @property
    def is_production(self) -> bool:
        return not self.DEBUG

    from pydantic import model_validator
    @model_validator(mode='after')
    def validate_secure_keys(self) -> 'Settings':
        """Ensure critical production keys are present and valid."""
        if not self.ENCRYPTION_KEY or len(self.ENCRYPTION_KEY) < 32:
            # Only allow missing version in local dev if not explicitly required
            if self.is_production:
                raise ValueError("ENCRYPTION_KEY must be at least 32 characters in production.")
        
        # Validate LLM Provider keys
        provider_keys = {
            "openai": self.OPENAI_API_KEY,
            "claude": self.CLAUDE_API_KEY,
            "anthropic": self.ANTHROPIC_API_KEY or self.CLAUDE_API_KEY, # Graceful migration
            "google": self.GOOGLE_API_KEY,
            "groq": self.GROQ_API_KEY
        }
        
        if self.LLM_PROVIDER in provider_keys and not provider_keys[self.LLM_PROVIDER]:
            # In production, we MUST have a key for the primary provider
            if self.is_production:
                raise ValueError(f"LLM_PROVIDER is set to '{self.LLM_PROVIDER}' but corresponding API key is missing.")
        
        return self

@lru_cache
def get_settings():
    """Returns a singleton instance of the application settings."""
    return Settings()
