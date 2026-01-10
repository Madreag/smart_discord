"""
Hybrid Query Agent: Multi-Source Response Generation

Combines multiple sources for comprehensive answers:
- Vector RAG: Discord conversation/document context
- Web Search: External/current information
- General Knowledge: LLM's training knowledge

Used when a single source isn't sufficient for a complete answer.
"""

import time
from typing import Optional
import asyncio

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from packages.shared.python.models import (
    AskResponse,
    MessageSource,
    RouterIntent,
)


async def process_hybrid_query(
    query: str,
    guild_id: int,
    channel_ids: Optional[list[int]] = None,
    channel_id: Optional[int] = None,
    include_vector: bool = True,
    include_web: bool = True,
    include_knowledge: bool = True,
) -> AskResponse:
    """
    Process a query using multiple sources for a comprehensive answer.
    
    Args:
        query: User's natural language query
        guild_id: Guild ID for filtering
        channel_ids: Optional channel filter for vector search
        channel_id: Current channel for conversation memory
        include_vector: Whether to search Discord context
        include_web: Whether to search the web
        include_knowledge: Whether to use general LLM knowledge
        
    Returns:
        Combined response with sources from all used pipelines
    """
    start_time = time.time()
    
    # Get conversation context for "that file" type references
    conversation_context = ""
    if channel_id:
        try:
            from apps.api.src.services.conversation_memory import conversation_memory
            conversation_context = conversation_memory.get_context(channel_id, max_messages=5)
            if conversation_context:
                print(f"[HYBRID] Using conversation context: {len(conversation_context)} chars")
        except Exception as e:
            print(f"[HYBRID] Error getting conversation context: {e}")
    
    context_sections = []
    all_sources = []
    tasks = []
    sources_used = []  # Track which sources actually returned content
    
    # Gather context from multiple sources in parallel
    if include_vector:
        tasks.append(("vector", _get_vector_context(query, guild_id, channel_ids)))
    
    if include_web:
        tasks.append(("web", _get_web_context(query)))
    
    # Execute searches in parallel
    if tasks:
        results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)
        
        for i, (source_type, _) in enumerate(tasks):
            result = results[i]
            if isinstance(result, Exception):
                print(f"[HYBRID] Error from {source_type}: {result}")
                continue
                
            context, sources = result
            if context:
                context_sections.append(f"## {source_type.title()} Context:\n{context}")
                all_sources.extend(sources)
                sources_used.append(source_type)
    
    # Always include knowledge if enabled
    if include_knowledge:
        sources_used.append("knowledge")
    
    # Generate final answer using all context
    combined_context = "\n\n".join(context_sections) if context_sections else ""
    
    answer = await _generate_combined_answer(
        query=query,
        context=combined_context,
        guild_id=guild_id,
        use_knowledge=include_knowledge,
        conversation_context=conversation_context,
    )
    
    execution_time = (time.time() - start_time) * 1000
    
    # Build routing label from sources used
    routing_label = " + ".join(sources_used) if sources_used else "knowledge"
    
    return AskResponse(
        answer=answer,
        sources=all_sources,
        routed_to=routing_label,  # Dynamic label like "vector + knowledge"
        execution_time_ms=execution_time,
    )


async def _get_vector_context(
    query: str,
    guild_id: int,
    channel_ids: Optional[list[int]] = None,
) -> tuple[str, list[MessageSource]]:
    """Get context from vector search (Discord messages/documents)."""
    try:
        from apps.api.src.agents.vector_rag import search_vectors
        import re
        
        results = await search_vectors(
            query=query,
            guild_id=guild_id,
            channel_ids=channel_ids,
            limit=5,
        )
        
        if not results:
            return "", []
        
        # Check if query is specifically about files/documents
        # If so, include results even with low semantic scores
        is_file_query = bool(re.search(
            r'\b(file|document|pdf|attachment|uploaded)\b', 
            query, re.IGNORECASE
        ))
        
        # Build context from results
        context_parts = []
        sources = []
        
        for r in results:
            payload = r.get("payload", {})
            score = r.get("score", 0)
            
            # For file queries, include documents even with low scores
            # For other queries, require higher relevance
            min_score = 0.0 if (is_file_query and payload.get("type") == "document") else 0.2
            if score < min_score:
                continue
            
            # Get content based on type
            if payload.get("type") == "document":
                # Document chunk
                text = payload.get("text", "")
                filename = payload.get("parent_file", "document")
                context_parts.append(f"[From {filename}]: {text}")
                sources.append(MessageSource(
                    message_id=int(payload.get("attachment_id", 0)),
                    channel_id=int(payload.get("channel_id", 0)),
                    content=text[:500],
                    relevance_score=score,
                    source_type="document",
                    parent_file=filename,
                ))
            else:
                # Chat session
                text = payload.get("content_preview", "")
                context_parts.append(f"[Discord chat]: {text}")
                # Extract first message_id from the session if available
                msg_ids = payload.get("message_ids", [])
                msg_id = int(msg_ids[0]) if msg_ids else 0
                sources.append(MessageSource(
                    message_id=msg_id,
                    channel_id=int(payload.get("channel_id", 0)),
                    content=text[:500],
                    relevance_score=score,
                    source_type="chat",
                ))
        
        return "\n\n".join(context_parts), sources
        
    except Exception as e:
        print(f"[HYBRID] Vector search error: {e}")
        return "", []


async def _get_web_context(query: str) -> tuple[str, list[MessageSource]]:
    """Get context from web search."""
    try:
        from apps.api.src.agents.web_search import search_web
        
        results = await search_web(query, num_results=3)
        
        if not results:
            return "", []
        
        # Build context from results
        context_parts = []
        sources = []
        
        for r in results:
            title = r.get("title", "")
            content = r.get("content", "")
            url = r.get("url", "")
            
            if content:
                context_parts.append(f"[{title}]: {content}")
                sources.append(MessageSource(
                    message_id=url,  # Use URL as ID
                    channel_id=0,
                    content_preview=f"{title}: {content[:150]}",
                    relevance_score=r.get("score", 0.5),
                ))
        
        return "\n\n".join(context_parts), sources
        
    except Exception as e:
        print(f"[HYBRID] Web search error: {e}")
        return "", []


async def _generate_combined_answer(
    query: str,
    context: str,
    guild_id: int,
    use_knowledge: bool = True,
    conversation_context: str = "",
) -> str:
    """Generate answer using all gathered context."""
    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        from datetime import datetime, timezone
        
        from apps.api.src.core.config import get_settings
        from apps.api.src.core.llm_factory import get_llm
        from apps.api.src.core.pre_prompt import get_guild_pre_prompt
        
        settings = get_settings()
        if not settings.active_llm_api_key:
            if context:
                return f"Based on available context:\n\n{context[:1000]}"
            return "I need an LLM API key configured to answer this question."
        
        llm = get_llm(temperature=0.3)
        
        current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        pre_prompt = get_guild_pre_prompt(guild_id)
        pre_prompt_section = f"\n\n{pre_prompt}" if pre_prompt else ""
        
        # Build conversation history section
        conversation_section = ""
        if conversation_context:
            conversation_section = f"""

RECENT CONVERSATION (use to understand references like "that file", "the document", etc.):
{conversation_context}
"""
        
        # Build system prompt based on available context
        if context:
            system_prompt = f"""You are a helpful Discord bot assistant. Answer the user's question using the provided context AND your general knowledge.

Current date and time: {current_time}{conversation_section}

CONTEXT FROM MULTIPLE SOURCES:
{context}

INSTRUCTIONS:
1. Use the context above as your primary source of information
2. Supplement with your general knowledge where the context is incomplete
3. If the context contains relevant information, cite or reference it
4. If the question asks about something not in the context, use your knowledge but note that you're drawing from general knowledge
5. Be helpful, accurate, and concise{pre_prompt_section}"""
        else:
            system_prompt = f"""You are a helpful Discord bot assistant that answers questions clearly and concisely.

Current date and time: {current_time}{conversation_section}

Answer the question using your knowledge. If you're uncertain about something, say so.{pre_prompt_section}"""
        
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=query),
        ])
        
        return response.content.strip()
        
    except Exception as e:
        if context:
            return f"Based on available context:\n\n{context[:1000]}"
        return f"Error generating response: {str(e)}"
