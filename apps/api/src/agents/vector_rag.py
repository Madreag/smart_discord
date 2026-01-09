"""
Vector RAG Agent: Semantic Search on Discord Messages

Performs vector similarity search on Qdrant for semantic/content queries.
Uses embeddings to find relevant message sessions and generates responses.

INVARIANT: All queries MUST filter by guild_id for multi-tenant isolation.
"""

import sys
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from packages.shared.python.models import (
    AskResponse,
    MessageSource,
    RouterIntent,
)
from packages.database.qdrant_schema import (
    SESSIONS_COLLECTION,
    MESSAGES_COLLECTION,
    validate_payload,
)


async def search_vectors(
    query: str,
    guild_id: int,
    collection_name: str = SESSIONS_COLLECTION,
    limit: int = 5,
    channel_ids: Optional[list[int]] = None,
    qdrant_client: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """
    Search Qdrant for semantically similar content.
    
    SECURITY: Always filters by guild_id for multi-tenant isolation.
    
    Args:
        query: Natural language query to search for
        guild_id: Guild ID for filtering (REQUIRED)
        collection_name: Qdrant collection to search
        limit: Maximum number of results
        channel_ids: Optional list of channel IDs to filter
        qdrant_client: Optional Qdrant client instance
        
    Returns:
        List of search results with payloads and scores
    """
    if qdrant_client is None:
        # Return empty results if no client (for testing)
        return []
    
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        # Build filter with REQUIRED guild_id
        must_conditions = [
            FieldCondition(
                key="guild_id",
                match=MatchValue(value=guild_id),
            )
        ]
        
        # Add optional channel filter
        if channel_ids:
            must_conditions.append(
                FieldCondition(
                    key="channel_id",
                    match=MatchValue(value=channel_ids[0]),  # Simplified for now
                )
            )
        
        query_filter = Filter(must=must_conditions)
        
        # Get embedding for query
        embedding = await _get_embedding(query)
        
        # Search Qdrant
        results = qdrant_client.search(
            collection_name=collection_name,
            query_vector=embedding,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        
        return [
            {
                "id": str(hit.id),
                "score": hit.score,
                "payload": hit.payload,
            }
            for hit in results
        ]
        
    except Exception as e:
        print(f"Vector search error: {e}")
        return []


async def _get_embedding(text: str) -> list[float]:
    """
    Get embedding vector for text using configured provider.
    
    Falls back to zero vector if unavailable (for testing).
    """
    try:
        from apps.api.src.core.llm_factory import get_embedding_model
        
        embedding_model = get_embedding_model()
        return embedding_model.embed_query(text)
        
    except Exception:
        # Return zero vector for testing/fallback
        return [0.0] * 384  # Default dimension for local embeddings


async def generate_rag_response(
    query: str,
    context_chunks: list[dict[str, Any]],
    guild_id: int,
) -> str:
    """
    Generate a response using retrieved context.
    
    Args:
        query: Original user query
        context_chunks: Retrieved context from vector search
        guild_id: Guild ID for context
        
    Returns:
        Generated response string
    """
    if not context_chunks:
        return "I couldn't find any relevant discussions matching your query."
    
    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        
        from apps.api.src.core.config import get_settings
        from apps.api.src.core.llm_factory import get_llm
        
        settings = get_settings()
        if not settings.active_llm_api_key:
            return _fallback_response(context_chunks)
        
        llm = get_llm(temperature=0.3)
        
        # Format context
        context_text = "\n\n".join([
            f"[Relevance: {chunk['score']:.2f}]\n{chunk['payload'].get('summary', chunk['payload'].get('content', ''))}"
            for chunk in context_chunks
        ])
        
        system_prompt = """You are a helpful assistant analyzing Discord community discussions.
Based on the retrieved context from the community's message history, answer the user's question.
Be concise and cite specific discussions when relevant.
If the context doesn't contain enough information, say so."""

        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Context:\n{context_text}\n\nQuestion: {query}"),
        ])
        
        return response.content.strip()
        
    except ImportError:
        return _fallback_response(context_chunks)
    except Exception as e:
        return f"Error generating response: {str(e)}"


def _fallback_response(context_chunks: list[dict[str, Any]]) -> str:
    """Fallback response when LLM is unavailable."""
    if not context_chunks:
        return "No relevant content found."
    
    summaries = [
        chunk['payload'].get('summary', chunk['payload'].get('content', ''))[:200]
        for chunk in context_chunks[:3]
    ]
    
    return f"Found {len(context_chunks)} relevant discussions:\n" + "\n".join(
        f"- {s}..." for s in summaries if s
    )


async def process_rag_query(
    query: str,
    guild_id: int,
    channel_ids: Optional[list[int]] = None,
    qdrant_client: Optional[Any] = None,
) -> AskResponse:
    """
    Process a semantic/RAG query and return formatted response.
    
    This is the main entry point for the Vector RAG agent.
    
    Args:
        query: Natural language query
        guild_id: Guild ID for filtering (REQUIRED)
        channel_ids: Optional channel filter
        qdrant_client: Optional Qdrant client
        
    Returns:
        AskResponse with answer and sources
    """
    import time
    start_time = time.time()
    
    # Search for relevant content
    results = await search_vectors(
        query=query,
        guild_id=guild_id,
        channel_ids=channel_ids,
        qdrant_client=qdrant_client,
    )
    
    # Generate response from context
    answer = await generate_rag_response(query, results, guild_id)
    
    # Convert results to MessageSource format
    sources = []
    for result in results:
        payload = result.get("payload", {})
        sources.append(
            MessageSource(
                message_id=payload.get("message_id", 0),
                channel_id=payload.get("channel_id", 0),
                author_id=payload.get("author_id", 0),
                content=payload.get("content", payload.get("summary", ""))[:500],
                timestamp=payload.get("timestamp", payload.get("start_time", "")),
                relevance_score=result.get("score", 0.0),
            )
        )
    
    execution_time = (time.time() - start_time) * 1000
    
    return AskResponse(
        answer=answer,
        sources=sources,
        routed_to=RouterIntent.VECTOR_RAG,
        execution_time_ms=execution_time,
    )
