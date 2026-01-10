"""
LLM Factory - Creates LLM and embedding instances based on configuration.
Supports OpenAI, Anthropic, and xAI (Grok) providers.
"""

from typing import List, Optional
from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from .config import get_settings, LLMProvider, EmbeddingProvider


def get_llm(
    temperature: float = 0.0,
    provider: Optional[LLMProvider] = None,
    with_thinking: Optional[bool] = None,
) -> BaseChatModel:
    """
    Get an LLM instance based on configuration or explicit provider.
    
    Args:
        temperature: Model temperature (0.0 = deterministic)
        provider: Override the configured provider
        with_thinking: Override thinking mode (None = use config setting)
        
    Returns:
        Configured LLM instance
    """
    settings = get_settings()
    active_provider = provider or settings.active_llm_provider
    active_model = settings.active_llm_model
    
    # Determine if thinking mode should be enabled
    thinking_enabled = with_thinking if with_thinking is not None else settings.active_thinking_enabled
    thinking_effort = settings.active_thinking_effort
    thinking_budget = settings.active_thinking_budget_tokens
    
    if active_provider == LLMProvider.OPENAI:
        from langchain_openai import ChatOpenAI
        
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when using OpenAI provider")
        
        # OpenAI o1/o3 models have built-in reasoning
        # For other models, reasoning_effort can be passed
        model_kwargs = {}
        if thinking_enabled and active_model.startswith(("o1", "o3")):
            model_kwargs["reasoning_effort"] = thinking_effort
        
        return ChatOpenAI(
            model=active_model,
            temperature=temperature,
            api_key=settings.openai_api_key,
            **({"model_kwargs": model_kwargs} if model_kwargs else {}),
        )
    
    elif active_provider == LLMProvider.ANTHROPIC:
        from langchain_anthropic import ChatAnthropic
        
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when using Anthropic provider")
        
        # Build kwargs - only add thinking params if enabled and supported
        kwargs = {
            "model": active_model,
            "temperature": temperature,
            "api_key": settings.anthropic_api_key,
        }
        
        # Extended thinking only works on Claude 4+ models
        if thinking_enabled and ("claude-4" in active_model or "claude-opus-4" in active_model or "claude-sonnet-4" in active_model):
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        
        return ChatAnthropic(**kwargs)
    
    elif active_provider == LLMProvider.XAI:
        from langchain_openai import ChatOpenAI
        
        if not settings.xai_api_key:
            raise ValueError("XAI_API_KEY is required when using xAI provider")
        
        # xAI grok-3-mini supports reasoning_effort
        model_kwargs = {}
        if thinking_enabled and "grok-3-mini" in active_model:
            model_kwargs["reasoning_effort"] = thinking_effort
        
        return ChatOpenAI(
            model=active_model,
            temperature=temperature,
            api_key=settings.xai_api_key,
            base_url=settings.xai_base_url,
            **({"model_kwargs": model_kwargs} if model_kwargs else {}),
        )
    
    raise ValueError(f"Unsupported LLM provider: {active_provider}")


# Available vision models per provider (updated January 2026)
AVAILABLE_VISION_MODELS = {
    "openai": [
        "gpt-5.2",
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
    ],
    "anthropic": [
        "claude-3-5-haiku-20241022",
        "claude-3-haiku-20240307",
    ],
    "xai": [
        "grok-2-vision-1212",
    ],
}

# Default vision model per provider
DEFAULT_VISION_MODELS = {
    LLMProvider.XAI: "grok-2-vision-1212",
    LLMProvider.ANTHROPIC: "claude-3-5-haiku-20241022",
    LLMProvider.OPENAI: "gpt-4o",
}


def get_vision_llm(
    provider: Optional[LLMProvider] = None,
    model: Optional[str] = None,
) -> BaseChatModel:
    """
    Get a vision-capable LLM for image/file processing.
    
    Supports:
    - xAI (Grok): grok-4.1-vision, grok-4-vision, grok-3-vision, grok-2-vision-1212
    - Anthropic (Claude): claude-opus-4-5, claude-sonnet-4-5, claude-haiku-4-5, etc.
    - OpenAI: gpt-5.2, gpt-4o, gpt-4o-mini
    
    Args:
        provider: Override the configured vision provider
        model: Override the configured vision model
        
    Returns:
        Vision-capable LLM instance
    """
    settings = get_settings()
    active_provider = provider or settings.active_vision_provider
    active_model = model or settings.active_vision_model
    
    # If no model specified, use default for provider
    if not active_model:
        active_model = DEFAULT_VISION_MODELS.get(active_provider)
    
    if not active_model:
        raise ValueError(f"No vision model configured for provider: {active_provider}")
    
    if active_provider == LLMProvider.OPENAI:
        from langchain_openai import ChatOpenAI
        
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI vision")
        
        return ChatOpenAI(
            model=active_model,
            api_key=settings.openai_api_key,
            max_tokens=1000,
        )
    
    elif active_provider == LLMProvider.ANTHROPIC:
        from langchain_anthropic import ChatAnthropic
        
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for Anthropic vision")
        
        return ChatAnthropic(
            model=active_model,
            api_key=settings.anthropic_api_key,
            max_tokens=1000,
        )
    
    elif active_provider == LLMProvider.XAI:
        from langchain_openai import ChatOpenAI
        
        if not settings.xai_api_key:
            raise ValueError("XAI_API_KEY is required for Grok vision")
        
        return ChatOpenAI(
            model=active_model,
            api_key=settings.xai_api_key,
            base_url=settings.xai_base_url,
            max_tokens=1000,
        )
    
    raise ValueError(f"Unsupported vision provider: {active_provider}")


class EmbeddingModel:
    """Unified embedding interface supporting multiple providers."""
    
    def __init__(self):
        self.settings = get_settings()
        self._model = None
        self._local_model = None
    
    def _get_openai_embedding(self) -> "OpenAIEmbeddings":
        """Get OpenAI embeddings model."""
        from langchain_openai import OpenAIEmbeddings
        
        if not self.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI embeddings")
        
        return OpenAIEmbeddings(
            model="text-embedding-3-small",
            api_key=self.settings.openai_api_key,
        )
    
    def _get_voyage_embedding(self):
        """Get Voyage AI embeddings model."""
        import voyageai
        
        if not self.settings.voyage_api_key:
            raise ValueError("VOYAGE_API_KEY is required for Voyage AI embeddings")
        
        return voyageai.Client(api_key=self.settings.voyage_api_key)
    
    def _get_local_model(self):
        """Get local sentence-transformers model (lazy loaded)."""
        if self._local_model is None:
            from sentence_transformers import SentenceTransformer
            self._local_model = SentenceTransformer(self.settings.active_embedding_model)
        return self._local_model
    
    def embed_query(self, text: str) -> List[float]:
        """Embed a single query text."""
        provider = self.settings.active_embedding_provider
        model_name = self.settings.active_embedding_model
        
        if provider == EmbeddingProvider.OPENAI:
            model = self._get_openai_embedding()
            return model.embed_query(text)
        elif provider == EmbeddingProvider.VOYAGE:
            client = self._get_voyage_embedding()
            result = client.embed([text], model=model_name, input_type="query")
            return result.embeddings[0]
        else:
            # Local embeddings with sentence-transformers
            model = self._get_local_model()
            embedding = model.encode(text, convert_to_numpy=True)
            return embedding.tolist()
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple documents."""
        provider = self.settings.active_embedding_provider
        model_name = self.settings.active_embedding_model
        
        if provider == EmbeddingProvider.OPENAI:
            model = self._get_openai_embedding()
            return model.embed_documents(texts)
        elif provider == EmbeddingProvider.VOYAGE:
            client = self._get_voyage_embedding()
            result = client.embed(texts, model=model_name, input_type="document")
            return result.embeddings
        else:
            # Local embeddings with sentence-transformers
            model = self._get_local_model()
            embeddings = model.encode(texts, convert_to_numpy=True)
            return [emb.tolist() for emb in embeddings]
    
    @property
    def dimension(self) -> int:
        """Get embedding dimension for the current model."""
        provider = self.settings.active_embedding_provider
        model_name = self.settings.active_embedding_model
        
        if provider == EmbeddingProvider.OPENAI:
            return 1536  # text-embedding-3-small
        elif provider == EmbeddingProvider.VOYAGE:
            # Voyage AI model dimensions
            voyage_dimensions = {
                "voyage-3-large": 1024,
                "voyage-3.5": 1024,
                "voyage-3.5-lite": 512,
                "voyage-code-3": 1024,
                "voyage-multilingual-2": 1024,
                "voyage-finance-2": 1024,
                "voyage-law-2": 1024,
            }
            return voyage_dimensions.get(model_name, 1024)
        else:
            # Common dimensions for sentence-transformers models
            model_dimensions = {
                "all-MiniLM-L6-v2": 384,
                "all-mpnet-base-v2": 768,
                "multi-qa-mpnet-base-dot-v1": 768,
            }
            return model_dimensions.get(model_name, 384)


@lru_cache
def get_embedding_model() -> EmbeddingModel:
    """Get cached embedding model instance."""
    return EmbeddingModel()


def get_provider_info() -> dict:
    """Get information about the current LLM configuration."""
    settings = get_settings()
    return {
        "llm_provider": settings.active_llm_provider.value,
        "llm_model": settings.active_llm_model,
        "embedding_provider": settings.active_embedding_provider.value,
        "embedding_model": settings.active_embedding_model,
        "has_api_key": settings.active_llm_api_key is not None,
    }
