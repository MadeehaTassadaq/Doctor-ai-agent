"""Application configuration via Pydantic BaseSettings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Environment-based configuration for the Doctor Service."""

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/doctorai"

    # Internal auth (shared secret with gateway)
    internal_auth_token: str = "dev-internal-token"

    # Service
    service_name: str = "doctor-service"
    environment: str = "development"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8003

    # Rate limiting
    rate_limit_general: int = 300
    rate_limit_window_seconds: int = 60

    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "ignore"}


settings = Settings()
