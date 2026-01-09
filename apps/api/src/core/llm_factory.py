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
) -> BaseChatModel:
    """
    Get an LLM instance based on configuration or explicit provider.
    
    Args:
        temperature: Model temperature (0.0 = deterministic)
        provider: Override the configured provider
        
    Returns:
        Configured LLM instance
    """
    settings = get_settings()
    active_provider = provider or settings.active_llm_provider
    active_model = settings.active_llm_model
    
    if active_provider == LLMProvider.OPENAI:
        from langchain_openai import ChatOpenAI
        
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when using OpenAI provider")
        
        return ChatOpenAI(
            model=active_model,
            temperature=temperature,
            api_key=settings.openai_api_key,
        )
    
    elif active_provider == LLMProvider.ANTHROPIC:
        from langchain_anthropic import ChatAnthropic
        
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when using Anthropic provider")
        
        return ChatAnthropic(
            model=active_model,
            temperature=temperature,
            api_key=settings.anthropic_api_key,
        )
    
    elif active_provider == LLMProvider.XAI:
        from langchain_openai import ChatOpenAI
        
        if not settings.xai_api_key:
            raise ValueError("XAI_API_KEY is required when using xAI provider")
        
        # xAI uses OpenAI-compatible API
        return ChatOpenAI(
            model=active_model,
            temperature=temperature,
            api_key=settings.xai_api_key,
            base_url=settings.xai_base_url,
        )
    
    raise ValueError(f"Unsupported LLM provider: {active_provider}")


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
    
    def _get_local_model(self):
        """Get local sentence-transformers model (lazy loaded)."""
        if self._local_model is None:
            from sentence_transformers import SentenceTransformer
            self._local_model = SentenceTransformer(self.settings.embedding_model)
        return self._local_model
    
    def embed_query(self, text: str) -> List[float]:
        """Embed a single query text."""
        if self.settings.embedding_provider == EmbeddingProvider.OPENAI:
            model = self._get_openai_embedding()
            return model.embed_query(text)
        else:
            # Local embeddings with sentence-transformers
            model = self._get_local_model()
            embedding = model.encode(text, convert_to_numpy=True)
            return embedding.tolist()
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple documents."""
        if self.settings.embedding_provider == EmbeddingProvider.OPENAI:
            model = self._get_openai_embedding()
            return model.embed_documents(texts)
        else:
            # Local embeddings with sentence-transformers
            model = self._get_local_model()
            embeddings = model.encode(texts, convert_to_numpy=True)
            return [emb.tolist() for emb in embeddings]
    
    @property
    def dimension(self) -> int:
        """Get embedding dimension for the current model."""
        if self.settings.embedding_provider == EmbeddingProvider.OPENAI:
            return 1536  # text-embedding-3-small
        else:
            # Common dimensions for sentence-transformers models
            model_dimensions = {
                "all-MiniLM-L6-v2": 384,
                "all-mpnet-base-v2": 768,
                "multi-qa-mpnet-base-dot-v1": 768,
            }
            return model_dimensions.get(self.settings.embedding_model, 384)


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
        "embedding_provider": settings.embedding_provider.value,
        "embedding_model": settings.embedding_model,
        "has_api_key": settings.active_llm_api_key is not None,
    }
