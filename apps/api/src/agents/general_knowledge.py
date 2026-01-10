"""
General Knowledge Agent: Direct LLM Response with Optional Web Search

Handles factual questions using LLM's training knowledge.
Can optionally augment responses with web search results for current information.
"""

import sys
from pathlib import Path
import time
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from packages.shared.python.models import (
    AskResponse,
    RouterIntent,
)


async def process_general_knowledge_query(
    query: str,
    guild_id: int,
    enable_web_search: bool = True,
) -> AskResponse:
    """
    Process a general knowledge query using direct LLM response.
    
    Args:
        query: Natural language factual question
        guild_id: Guild ID (for logging/tracking only)
        
    Returns:
        AskResponse with answer from LLM
    """
    start_time = time.time()
    web_context = ""
    
    # Optionally fetch web search context
    if enable_web_search:
        web_context = await _get_web_search_context(query)
    
    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        
        from apps.api.src.core.config import get_settings
        from apps.api.src.core.llm_factory import get_llm
        
        settings = get_settings()
        if not settings.active_llm_api_key:
            return AskResponse(
                answer="I need an LLM API key configured to answer general knowledge questions.",
                sources=[],
                routed_to=RouterIntent.GENERAL_KNOWLEDGE,
                execution_time_ms=(time.time() - start_time) * 1000,
            )
        
        llm = get_llm(temperature=0.3)
        
        current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # Fetch guild pre-prompt for personality injection
        from apps.api.src.core.pre_prompt import get_guild_pre_prompt
        pre_prompt = get_guild_pre_prompt(guild_id)
        pre_prompt_section = f"\n\n{pre_prompt}" if pre_prompt else ""
        
        # Build web context section if available
        web_section = ""
        if web_context:
            web_section = f"""

WEB SEARCH RESULTS (use for current/recent information):
{web_context}

When answering, incorporate relevant information from web search results where applicable."""
        
        system_prompt = f"""You are a helpful Discord bot assistant that answers questions clearly and concisely.

IMPORTANT: You have access to the current date and time. When asked about the time, date, or day, USE THIS INFORMATION:
Current date and time: {current_time}

For time-related questions, provide the answer using the timestamp above. Convert to the user's likely timezone if they mention one, otherwise give UTC time.

For factual questions, provide accurate answers based on your knowledge. If you're genuinely uncertain about something, say so.{web_section}{pre_prompt_section}"""

        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=query),
        ])
        
        answer = response.content.strip()
        
    except ImportError:
        answer = "LangChain is not available. Please install it to enable general knowledge queries."
    except Exception as e:
        answer = f"Error processing query: {str(e)}"
    
    execution_time = (time.time() - start_time) * 1000
    
    return AskResponse(
        answer=answer,
        sources=[],
        routed_to=RouterIntent.GENERAL_KNOWLEDGE,
        execution_time_ms=execution_time,
    )


async def _get_web_search_context(query: str) -> str:
    """
    Fetch web search context for the query.
    
    Returns formatted context string or empty string if unavailable.
    """
    try:
        from apps.api.src.agents.web_search import search_web
        
        results = await search_web(query, num_results=3)
        
        if not results:
            return ""
        
        # Format results as context
        context_parts = []
        for r in results:
            title = r.get("title", "")
            content = r.get("content", "")
            url = r.get("url", "")
            
            if content:
                context_parts.append(f"- [{title}]({url}): {content[:300]}")
        
        if context_parts:
            print(f"[GENERAL_KNOWLEDGE] Added web context from {len(context_parts)} sources")
            return "\n".join(context_parts)
        
        return ""
        
    except Exception as e:
        print(f"[GENERAL_KNOWLEDGE] Web search error: {e}")
        return ""
