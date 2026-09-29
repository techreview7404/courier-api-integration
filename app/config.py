"""Application configuration management using Pydantic Settings."""

from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables and .env file."""

    # Application
    APP_NAME: str = "Courier Integration Platform"
    DEBUG: bool = False

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, v: object) -> bool:
        """Parse debug flag safely even when set to loglevel strings like 'WARN'."""
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "on", "debug")
        return bool(v)

    # Database
    DATABASE_URL: str = "sqlite:///./app.db"

    # Resiliency & Retry Policies
    MAX_RETRIES: int = 3
    RETRY_DELAY: float = 1.0
    REQUEST_TIMEOUT: float = 10.0

    # Bulk Concurrency
    BULK_CONCURRENCY_LIMIT: int = 10

    # UrbaneBolt Credentials & Settings
    URBANEBOLT_BASE_URL: str = "https://uat.urbanebolt.in"
    URBANEBOLT_API_KEY: str = ""
    URBANEBOLT_USERNAME: str = ""
    URBANEBOLT_PASSWORD: str = ""
    URBANEBOLT_CUSTOMER_CODE: str = "UEBCUS0008"

    # Default Shipper Details for Manifest Generation
    SHIPPER_NAME: str = "Central Warehouse"
    SHIPPER_MOBILE: int = 9999999999
    SHIPPER_EMAIL: str = "warehouse@example.com"
    SHIPPER_ADDRESS: str = "Industrial Area Phase 1"
    SHIPPER_CITY: str = "Gurgaon"
    SHIPPER_STATE: str = "HARYANA"
    SHIPPER_PINCODE: int = 122001

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()


settings = get_settings()
