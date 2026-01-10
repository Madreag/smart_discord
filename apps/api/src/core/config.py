"""
Application configuration using Pydantic Settings.
"""

import json
import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
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
    VOYAGE = "voyage"
    LOCAL = "local"


# Runtime overrides for settings that can be changed without restart
_runtime_overrides: dict[str, str] = {}

# Path to persistent settings file
_SETTINGS_FILE = Path(__file__).parent.parent.parent.parent.parent / "data" / "settings.json"


def _load_persistent_settings() -> None:
    """Load settings from persistent storage on startup."""
    global _runtime_overrides
    if _SETTINGS_FILE.exists():
        try:
            with open(_SETTINGS_FILE, "r") as f:
                _runtime_overrides = json.load(f)
        except (json.JSONDecodeError, IOError):
            _runtime_overrides = {}


def _save_persistent_settings() -> None:
    """Save current settings to persistent storage."""
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_SETTINGS_FILE, "w") as f:
        json.dump(_runtime_overrides, f, indent=2)


# Load settings on module import
_load_persistent_settings()


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
    vision_provider: LLMProvider = LLMProvider.XAI  # Default to Grok for vision/file processing
    vision_model: Optional[str] = None  # If None, uses default for provider
    
    # Thinking/Reasoning Mode Settings
    thinking_enabled: bool = False  # Enable extended thinking/reasoning
    thinking_effort: str = "medium"  # "low", "medium", "high"
    thinking_budget_tokens: int = 2000  # Budget for Claude extended thinking
    
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
    
    # Voyage AI
    voyage_api_key: Optional[str] = None
    
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
    def active_llm_provider(self) -> LLMProvider:
        """Get the active LLM provider (runtime override or env)."""
        if "llm_provider" in _runtime_overrides:
            return LLMProvider(_runtime_overrides["llm_provider"])
        return self.llm_provider
    
    @property
    def active_vision_provider(self) -> LLMProvider:
        """Get the active vision provider for file/image processing."""
        if "vision_provider" in _runtime_overrides:
            return LLMProvider(_runtime_overrides["vision_provider"])
        return self.vision_provider
    
    @property
    def active_vision_model(self) -> Optional[str]:
        """Get the active vision model for file/image processing."""
        if "vision_model" in _runtime_overrides:
            return _runtime_overrides["vision_model"]
        return self.vision_model
    
    @property
    def active_thinking_enabled(self) -> bool:
        """Get whether thinking mode is enabled."""
        if "thinking_enabled" in _runtime_overrides:
            return _runtime_overrides["thinking_enabled"].lower() == "true"
        return self.thinking_enabled
    
    @property
    def active_thinking_effort(self) -> str:
        """Get the thinking effort level (low, medium, high)."""
        if "thinking_effort" in _runtime_overrides:
            return _runtime_overrides["thinking_effort"]
        return self.thinking_effort
    
    @property
    def active_thinking_budget_tokens(self) -> int:
        """Get the thinking budget tokens for Claude."""
        if "thinking_budget_tokens" in _runtime_overrides:
            return int(_runtime_overrides["thinking_budget_tokens"])
        return self.thinking_budget_tokens
    
    @property
    def active_embedding_provider(self) -> EmbeddingProvider:
        """Get the active embedding provider (runtime override or env)."""
        if "embedding_provider" in _runtime_overrides:
            return EmbeddingProvider(_runtime_overrides["embedding_provider"])
        return self.embedding_provider
    
    @property
    def active_embedding_model(self) -> str:
        """Get the active embedding model (runtime override or env)."""
        if "embedding_model" in _runtime_overrides:
            return _runtime_overrides["embedding_model"]
        return self.embedding_model
    
    @property
    def active_llm_api_key(self) -> Optional[str]:
        """Get the API key for the currently selected LLM provider."""
        provider = self.active_llm_provider
        if provider == LLMProvider.OPENAI:
            return _runtime_overrides.get("openai_api_key") or self.openai_api_key
        elif provider == LLMProvider.ANTHROPIC:
            return _runtime_overrides.get("anthropic_api_key") or self.anthropic_api_key
        elif provider == LLMProvider.XAI:
            return _runtime_overrides.get("xai_api_key") or self.xai_api_key
        return None
    
    def get_api_key_for_provider(self, provider: str) -> Optional[str]:
        """Get API key for a specific provider."""
        key_map = {
            "openai": _runtime_overrides.get("openai_api_key") or self.openai_api_key,
            "anthropic": _runtime_overrides.get("anthropic_api_key") or self.anthropic_api_key,
            "xai": _runtime_overrides.get("xai_api_key") or self.xai_api_key,
            "tavily": _runtime_overrides.get("tavily_api_key") or self.tavily_api_key,
            "voyage": _runtime_overrides.get("voyage_api_key") or self.voyage_api_key,
        }
        return key_map.get(provider)
    
    @property
    def active_llm_model(self) -> str:
        """Get the model name for the currently selected LLM provider."""
        provider = self.active_llm_provider
        # Check for runtime model override
        model_key = f"{provider.value}_model"
        if model_key in _runtime_overrides:
            return _runtime_overrides[model_key]
        # Fall back to env-based model
        if provider == LLMProvider.OPENAI:
            return self.openai_model
        elif provider == LLMProvider.ANTHROPIC:
            return self.anthropic_model
        elif provider == LLMProvider.XAI:
            return self.xai_model
        return self.openai_model


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def clear_settings_cache() -> None:
    """Clear the settings cache (useful when settings change at runtime)."""
    get_settings.cache_clear()


def set_runtime_override(key: str, value: str) -> None:
    """Set a runtime override for a setting and persist to disk."""
    _runtime_overrides[key] = value
    _save_persistent_settings()


def get_runtime_overrides() -> dict[str, str]:
    """Get all runtime overrides."""
    return _runtime_overrides.copy()
