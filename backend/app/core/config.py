"""Bootstrap settings loaded from environment.

For runtime-editable settings (chat limits, active LLM provider, etc.),
see app.core.settings_store.SettingsStore — those live in Postgres + Redis.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me"
    ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1"]
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    DATABASE_URL: str = "postgresql+psycopg2://cpmai:cpmai_dev@postgres:5432/cpmai_prep"
    REDIS_URL: str = "redis://redis:6379/0"

    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""

    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    ENCRYPTION_KEY: str = ""

    BOOTSTRAP_ADMIN_EMAIL: str = ""
    BOOTSTRAP_ADMIN_PASSWORD: str = ""

    ASSISTANT_FALLBACK_PROVIDER: str = "stub"


settings = Settings()
