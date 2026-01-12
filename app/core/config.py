from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    APP_NAME: str = "CloudSentinel"
    VERSION: str = "0.1.0"
    DEBUG: bool = False
    
    # AWS Credentials
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_DEFAULT_REGION: str = "us-east-1"
    
    # Security
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"]
    ENCRYPTION_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o" # High performance for complex analysis

    # Claude Credentials
    CLAUDE_API_KEY: Optional[str] = None
    CLAUDE_MODEL: str = "claude-3-7-sonnet"

    # Google Gemini Credentials
    GOOGLE_API_KEY: Optional[str] = None
    GOOGLE_MODEL: str = "gemini-2.0-flash"

    # Groq Credentials
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # LLM Provider
    LLM_PROVIDER: str = "groq" # Options: openai, claude, google, groq

    # Scheduler
    SCHEDULER_HOUR: int = 8
    SCHEDULER_MINUTE: int = 0

    # Admin API Key
    ADMIN_API_KEY: Optional[str] = None

    # Database
    DATABASE_URL: str # Required in prod

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
    SMTP_FROM: str = "alerts@cloudsentinel.io"
    
    # Encryption
    ENCRYPTION_KEY: Optional[str] = None
    
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_ignore_empty=True
    )

@lru_cache
def get_settings():
    return Settings()