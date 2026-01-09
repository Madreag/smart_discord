"""
Bot configuration using Pydantic Settings.
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    """Bot settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Discord
    discord_token: str
    discord_client_id: Optional[str] = None
    
    # API
    api_base_url: str = "http://localhost:8000"
    
    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/smart_discord"
    
    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: Optional[str] = None
    
    # Redis/Celery
    redis_url: str = "redis://localhost:6379"
    celery_broker_url: Optional[str] = None
    
    @property
    def broker_url(self) -> str:
        """Get Celery broker URL."""
        return self.celery_broker_url or self.redis_url


@lru_cache
def get_bot_settings() -> BotSettings:
    """Get cached bot settings instance."""
    return BotSettings()
