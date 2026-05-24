"""Application configuration via Pydantic BaseSettings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Environment-based configuration for the API Gateway."""

    # Supabase Auth
    supabase_jwks_url: str = "https://<project>.supabase.co/auth/v1/.well-known/jwks.json"
    supabase_project_ref: str = ""
    supabase_webhook_secret: str = ""
    supabase_service_role_key: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/doctorai"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Gateway
    frontend_url: str = "http://localhost:3000"
    environment: str = "development"
    log_level: str = "INFO"

    # Rate limiting (single tier for MVP)
    rate_limit_general: int = 300
    rate_limit_window_seconds: int = 60

    # Internal auth (plain headers for MVP)
    internal_auth_token: str = "dev-internal-token"

    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "ignore"}


settings = Settings()
