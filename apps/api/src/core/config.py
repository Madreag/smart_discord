"""
Application configuration using Pydantic Settings.
"""

from enum import Enum
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    """Supported LLM providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    XAI = "xai"


class EmbeddingProvider(str, Enum):
    """Supported embedding providers."""
    OPENAI = "openai"
    LOCAL = "local"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/smart_discord"
    database_readonly_url: Optional[str] = None
    
    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: Optional[str] = None
    
    # Redis
    redis_url: str = "redis://localhost:6379"
    
    # LLM Provider Selection
    llm_provider: LLMProvider = LLMProvider.OPENAI
    
    # OpenAI
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    
    # Anthropic
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-sonnet-4-20250514"
    
    # xAI (Grok)
    xai_api_key: Optional[str] = None
    xai_model: str = "grok-beta"
    xai_base_url: str = "https://api.x.ai/v1"
    
    # Embeddings
    embedding_provider: EmbeddingProvider = EmbeddingProvider.LOCAL
    embedding_model: str = "all-MiniLM-L6-v2"
    
    # Tavily (web search)
    tavily_api_key: Optional[str] = None
    
    # Discord Bot (for fetching guild channels)
    discord_token: Optional[str] = None
    
    # Application
    debug: bool = False
    
    @property
    def readonly_db_url(self) -> str:
        """Get read-only database URL, falling back to primary if not set."""
        return self.database_readonly_url or self.database_url
    
    @property
    def active_llm_api_key(self) -> Optional[str]:
        """Get the API key for the currently selected LLM provider."""
        if self.llm_provider == LLMProvider.OPENAI:
            return self.openai_api_key
        elif self.llm_provider == LLMProvider.ANTHROPIC:
            return self.anthropic_api_key
        elif self.llm_provider == LLMProvider.XAI:
            return self.xai_api_key
        return None
    
    @property
    def active_llm_model(self) -> str:
        """Get the model name for the currently selected LLM provider."""
        if self.llm_provider == LLMProvider.OPENAI:
            return self.openai_model
        elif self.llm_provider == LLMProvider.ANTHROPIC:
            return self.anthropic_model
        elif self.llm_provider == LLMProvider.XAI:
            return self.xai_model
        return self.openai_model


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def clear_settings_cache() -> None:
    """Clear the settings cache (useful when settings change at runtime)."""
    get_settings.cache_clear()
