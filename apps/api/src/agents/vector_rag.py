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
    use_hybrid: bool = True,
    use_reranking: bool = True,
) -> list[dict[str, Any]]:
    """
    Search Qdrant for semantically similar content using hybrid search.
    
    SECURITY: Always filters by guild_id for multi-tenant isolation.
    
    Hybrid search combines:
    1. Dense vectors (semantic similarity)
    2. Sparse vectors (BM25 keyword matching)
    3. RRF fusion to combine results
    4. Late interaction reranking for highest quality
    
    Args:
        query: Natural language query to search for
        guild_id: Guild ID for filtering (REQUIRED)
        collection_name: Qdrant collection to search
        limit: Maximum number of results
        channel_ids: Optional list of channel IDs to filter
        qdrant_client: Optional Qdrant client instance (ignored, uses service)
        use_hybrid: Whether to use hybrid search (default True)
        use_reranking: Whether to apply late interaction reranking (default True)
        
    Returns:
        List of search results with payloads and scores
    """
    try:
        from apps.api.src.services.qdrant_service import qdrant_service
        import re
        
        # Detect if query mentions attachments/files - search documents first
        attachment_pattern = r'\[Attachments?:\s*([^\]]+)\]'
        attachment_match = re.search(attachment_pattern, query, re.IGNORECASE)
        
        # Also detect file-related keywords
        file_keywords = r'\b(file|document|pdf|report|attachment|attached|uploaded)\b'
        mentions_file = re.search(file_keywords, query, re.IGNORECASE)
        
        # Clean query for embedding
        clean_query = re.sub(attachment_pattern, '', query).strip()
        search_query = clean_query if clean_query else query
        
        results = []
        
        # Try hybrid search first if enabled
        if use_hybrid:
            results = await _hybrid_search(
                query=search_query,
                guild_id=guild_id,
                channel_ids=channel_ids,
                limit=limit * 2 if use_reranking else limit,  # Oversample for reranking
                source_types=['pdf', 'markdown', 'text', 'image'] if (attachment_match or mentions_file) else None,
            )
            
            if results:
                print(f"[VECTOR_RAG] Hybrid search found {len(results)} results")
        
        # Fallback to legacy dense-only search if hybrid fails or returns nothing
        if not results:
            results = await _legacy_search(
                query=search_query,
                guild_id=guild_id,
                channel_ids=channel_ids,
                limit=limit,
                source_types=['pdf', 'markdown', 'text', 'image'] if (attachment_match or mentions_file) else None,
            )
        
        # Apply late interaction reranking if enabled and we have results
        if use_reranking and results and len(results) > 1:
            results = _apply_reranking(search_query, results, limit)
        
        return results[:limit]
        
    except Exception as e:
        print(f"Vector search error: {e}")
        import traceback
        traceback.print_exc()
        return []


async def _hybrid_search(
    query: str,
    guild_id: int,
    channel_ids: Optional[list[int]] = None,
    limit: int = 10,
    source_types: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """
    Perform hybrid search using dense + sparse vectors with RRF fusion.
    """
    try:
        from apps.api.src.services.qdrant_service import qdrant_service
        from apps.api.src.services.hybrid_embedding import get_hybrid_embedding_model
        
        # Get hybrid embeddings (dense + sparse)
        hybrid_model = get_hybrid_embedding_model()
        hybrid_embedding = hybrid_model.embed_query(query)
        
        # Perform hybrid search with RRF fusion
        results = qdrant_service.hybrid_search(
            query_dense=hybrid_embedding.dense,
            query_sparse_indices=hybrid_embedding.sparse_indices,
            query_sparse_values=hybrid_embedding.sparse_values,
            guild_id=guild_id,
            channel_ids=channel_ids,
            limit=limit,
            source_types=source_types,
        )
        
        return results
        
    except Exception as e:
        print(f"[VECTOR_RAG] Hybrid search failed: {e}")
        return []


async def _legacy_search(
    query: str,
    guild_id: int,
    channel_ids: Optional[list[int]] = None,
    limit: int = 5,
    source_types: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """
    Fallback to legacy dense-only search.
    """
    try:
        from apps.api.src.services.qdrant_service import qdrant_service
        from apps.api.src.core.llm_factory import get_embedding_model
        
        embedding_model = get_embedding_model()
        query_embedding = embedding_model.embed_query(query)
        
        results = qdrant_service.search(
            query_embedding=query_embedding,
            guild_id=guild_id,
            channel_ids=channel_ids,
            limit=limit,
            source_types=source_types,
        )
        
        return results
        
    except Exception as e:
        print(f"[VECTOR_RAG] Legacy search failed: {e}")
        return []


def _apply_reranking(
    query: str,
    results: list[dict[str, Any]],
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """
    Apply late interaction reranking to improve result quality.
    """
    try:
        from apps.api.src.services.hybrid_embedding import get_late_interaction_model
        
        reranker = get_late_interaction_model()
        if reranker.enabled:
            reranked = reranker.rerank(query, results, top_k=top_k)
            print(f"[VECTOR_RAG] Reranked {len(results)} results to top {len(reranked)}")
            return reranked
        
        return results[:top_k]
        
    except Exception as e:
        print(f"[VECTOR_RAG] Reranking failed: {e}")
        return results[:top_k]


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
    recent_messages_context: str = "",
) -> str:
    """
    Generate a response using retrieved context.
    
    Args:
        query: Original user query
        context_chunks: Retrieved context from vector search (long-term/Qdrant)
        guild_id: Guild ID for context
        recent_messages_context: Last 30 channel messages from Postgres (short-term memory)
        
    Returns:
        Generated response string
    """
    if not context_chunks and not recent_messages_context:
        return "I couldn't find any relevant discussions matching your query."
    
    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        
        from apps.api.src.core.config import get_settings
        from apps.api.src.core.llm_factory import get_llm
        
        settings = get_settings()
        if not settings.active_llm_api_key:
            return _fallback_response(context_chunks)
        
        llm = get_llm(temperature=0.3)
        
        # Format context from vector search (supports both chat sessions and document chunks)
        context_text = ""
        if context_chunks:
            formatted_chunks = []
            for chunk in context_chunks:
                payload = chunk['payload']
                # Document chunks use 'text', chat sessions use 'summary' or 'content'
                text = payload.get('text', payload.get('summary', payload.get('content', '')))
                source_type = payload.get('source_type', 'chat')
                parent_file = payload.get('parent_file', '')
                
                if source_type != 'chat' and parent_file:
                    formatted_chunks.append(f"[Source: {parent_file}, Relevance: {chunk['score']:.2f}]\n{text}")
                else:
                    formatted_chunks.append(f"[Relevance: {chunk['score']:.2f}]\n{text}")
            
            context_text = "\n\n".join(formatted_chunks)
        
        # Fetch guild pre-prompt for personality injection
        from apps.api.src.core.pre_prompt import get_guild_pre_prompt
        pre_prompt = get_guild_pre_prompt(guild_id)
        pre_prompt_section = f"\n\n{pre_prompt}" if pre_prompt else ""
        
        # Add recent channel messages (short-term memory from Postgres - respects deletions)
        recent_section = ""
        if recent_messages_context:
            recent_section = f"\n\nRecent channel messages (last 30):\n{recent_messages_context}"
        
        system_prompt = f"""You are a helpful assistant analyzing Discord community discussions.
Answer the user's question using the provided context.

Priority for answering:
1. First check "Recent channel messages" - these are the most current discussions
2. Then check "Historical context" from the archive for older information

Be concise and cite specific messages when relevant.
If the context doesn't contain enough information, say so.{pre_prompt_section}"""

        # Build user content with recent messages taking priority
        user_content = ""
        if recent_section:
            user_content += recent_section
        if context_text:
            user_content += f"\n\nHistorical context from archive:\n{context_text}"
        user_content += f"\n\nQuestion: {query}"

        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
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
    
    summaries = []
    for chunk in context_chunks[:3]:
        payload = chunk['payload']
        # Support document chunks (text) and chat sessions (summary/content)
        text = payload.get('text', payload.get('summary', payload.get('content', '')))[:200]
        parent_file = payload.get('parent_file', '')
        if parent_file:
            summaries.append(f"[{parent_file}] {text}")
        else:
            summaries.append(text)
    
    return f"Found {len(context_chunks)} relevant results:\n" + "\n".join(
        f"- {s}..." for s in summaries if s
    )


async def process_rag_query(
    query: str,
    guild_id: int,
    channel_ids: Optional[list[int]] = None,
    qdrant_client: Optional[Any] = None,
    channel_id: Optional[int] = None,
) -> AskResponse:
    """
    Process a semantic/RAG query and return formatted response.
    
    This is the main entry point for the Vector RAG agent.
    
    Strategy:
    1. First check recent messages (last 30) from the current channel - no RAG needed
    2. If no matches found, fall back to Qdrant vector search for long-term memory
    
    Args:
        query: Natural language query
        guild_id: Guild ID for filtering (REQUIRED)
        channel_ids: Optional channel filter
        qdrant_client: Optional Qdrant client
        channel_id: Optional current channel ID for recent message lookup
        
    Returns:
        AskResponse with answer and sources
    """
    import time
    start_time = time.time()
    
    # Get recent messages from Postgres (authoritative, respects deletions)
    recent_messages_context = ""
    
    if channel_id:
        try:
            from apps.api.src.services.conversation_memory import (
                get_recent_channel_messages,
                format_recent_messages_as_context,
            )
            
            # Get last 30 messages from the channel (short-term memory)
            # This is from Postgres which properly handles deletions (Right to be Forgotten)
            recent_messages = get_recent_channel_messages(
                guild_id=guild_id,
                channel_id=channel_id,
                limit=30,
            )
            
            if recent_messages:
                recent_messages_context = format_recent_messages_as_context(recent_messages)
                print(f"[VECTOR_RAG] Using {len(recent_messages)} recent messages as short-term context")
        except Exception as e:
            print(f"[VECTOR_RAG] Error fetching recent messages: {e}")
    
    # Search Qdrant for long-term memory (historical content)
    results = await search_vectors(
        query=query,
        guild_id=guild_id,
        channel_ids=channel_ids,
        qdrant_client=qdrant_client,
    )
    
    # Generate response from context (recent messages + RAG results)
    answer = await generate_rag_response(
        query=query,
        context_chunks=results,
        guild_id=guild_id,
        recent_messages_context=recent_messages_context,
    )
    
    # Convert results to MessageSource format (supports both chat and document sources)
    sources = []
    for result in results:
        payload = result.get("payload", {})
        source_type = payload.get("source_type", "chat")
        
        # Get content - document chunks use 'text', chat uses 'content' or 'summary'
        content = payload.get("text", payload.get("content", payload.get("summary", "")))[:500]
        
        # Get timestamp - may be None for document chunks
        timestamp_str = payload.get("timestamp", payload.get("start_time"))
        timestamp = None
        if timestamp_str:
            try:
                from datetime import datetime
                if isinstance(timestamp_str, str):
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                else:
                    timestamp = timestamp_str
            except (ValueError, TypeError):
                timestamp = None
        
        sources.append(
            MessageSource(
                message_id=payload.get("message_id", payload.get("attachment_id", 0)),
                channel_id=payload.get("channel_id", 0),
                author_id=payload.get("author_id", 0),
                content=content,
                timestamp=timestamp,
                relevance_score=result.get("score", 0.0),
                source_type=source_type,
                parent_file=payload.get("parent_file"),
            )
        )
    
    execution_time = (time.time() - start_time) * 1000
    
    return AskResponse(
        answer=answer,
        sources=sources,
        routed_to=RouterIntent.VECTOR_RAG,
        execution_time_ms=execution_time,
    )
