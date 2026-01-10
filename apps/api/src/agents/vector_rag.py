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
        qdrant_client: Optional Qdrant client instance (ignored, uses service)
        
    Returns:
        List of search results with payloads and scores
    """
    try:
        from apps.api.src.services.qdrant_service import qdrant_service
        from apps.api.src.core.llm_factory import get_embedding_model
        import re
        
        # Detect if query mentions attachments/files - search documents first
        attachment_pattern = r'\[Attachments?:\s*([^\]]+)\]'
        attachment_match = re.search(attachment_pattern, query, re.IGNORECASE)
        
        # Also detect file-related keywords
        file_keywords = r'\b(file|document|pdf|report|attachment|attached|uploaded)\b'
        mentions_file = re.search(file_keywords, query, re.IGNORECASE)
        
        # Get embedding for query (use clean query for better matching)
        clean_query = re.sub(attachment_pattern, '', query).strip()
        embedding_model = get_embedding_model()
        query_embedding = embedding_model.embed_query(clean_query if clean_query else query)
        
        results = []
        
        # If attachments mentioned, search documents first with lower threshold
        if attachment_match or mentions_file:
            print(f"[VECTOR_RAG] Detected document query, searching document chunks first")
            doc_results = qdrant_service.search(
                query_embedding=query_embedding,
                guild_id=guild_id,
                channel_ids=channel_ids,
                limit=limit,
                score_threshold=0.0,  # Lower threshold for documents
                source_types=['pdf', 'markdown', 'text', 'image'],
            )
            results.extend(doc_results)
            
            # If we found documents, return them; otherwise fall back to chat
            if results:
                print(f"[VECTOR_RAG] Found {len(results)} document chunks")
                return results
        
        # Standard search (chat messages + documents)
        results = qdrant_service.search(
            query_embedding=query_embedding,
            guild_id=guild_id,
            channel_ids=channel_ids,
            limit=limit,
        )
        
        return results
        
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
    conversation_context: str = "",
) -> str:
    """
    Generate a response using retrieved context.
    
    Args:
        query: Original user query
        context_chunks: Retrieved context from vector search
        guild_id: Guild ID for context
        conversation_context: Recent conversation history for session continuity
        
    Returns:
        Generated response string
    """
    if not context_chunks and not conversation_context:
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
        
        # Add conversation context section
        conversation_section = ""
        if conversation_context:
            conversation_section = f"\n\nRecent conversation in this channel:\n{conversation_context}"
        
        system_prompt = f"""You are a helpful assistant analyzing Discord community discussions.
Based on the retrieved context from the community's message history, answer the user's question.
Be concise and cite specific discussions when relevant.
If the context doesn't contain enough information, say so.
You can reference your previous answers in the current conversation if relevant.{pre_prompt_section}"""

        user_content = f"Context from message history:\n{context_text}" if context_text else ""
        if conversation_section:
            user_content += conversation_section
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
    
    # Get conversation context if channel_id provided
    conversation_context = ""
    if channel_id:
        try:
            from apps.api.src.services.conversation_memory import conversation_memory
            conversation_context = conversation_memory.get_context(channel_id, max_messages=5)
        except Exception:
            pass
    
    # Search for relevant content
    results = await search_vectors(
        query=query,
        guild_id=guild_id,
        channel_ids=channel_ids,
        qdrant_client=qdrant_client,
    )
    
    # Generate response from context
    answer = await generate_rag_response(query, results, guild_id, conversation_context)
    
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
