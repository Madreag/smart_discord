"""
Web Search Agent: External Information Retrieval

Handles queries requiring information from outside the Discord community,
such as current events, documentation, or real-time data.
"""

import sys
from pathlib import Path
from typing import Any, Optional
import time

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from packages.shared.python.models import (
    AskResponse,
    MessageSource,
    RouterIntent,
)


async def search_web(
    query: str,
    num_results: int = 5,
) -> list[dict[str, Any]]:
    """
    Search the web for information.
    
    Uses a web search API (e.g., Tavily, Serper, or similar).
    Falls back to empty results if no API configured.
    
    Args:
        query: Search query
        num_results: Maximum number of results
        
    Returns:
        List of search results with title, url, and snippet
    """
    try:
        # Try Tavily first (preferred for LLM applications)
        from tavily import TavilyClient
        from apps.api.src.core.config import get_settings
        
        settings = get_settings()
        tavily_key = getattr(settings, 'tavily_api_key', None)
        
        if tavily_key:
            client = TavilyClient(api_key=tavily_key)
            response = client.search(query, max_results=num_results)
            
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                    "score": r.get("score", 0.0),
                }
                for r in response.get("results", [])
            ]
    except ImportError:
        pass
    except Exception:
        pass
    
    # Fallback: return empty (would use alternative API in production)
    return []


async def generate_web_response(
    query: str,
    search_results: list[dict[str, Any]],
) -> str:
    """
    Generate a response based on web search results.
    
    Args:
        query: Original user query
        search_results: Results from web search
        
    Returns:
        Generated response string
    """
    if not search_results:
        return (
            "I wasn't able to search the web for this information. "
            "Please try searching directly or check if web search is configured."
        )
    
    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        
        from apps.api.src.core.config import get_settings
        from apps.api.src.core.llm_factory import get_llm
        
        settings = get_settings()
        if not settings.active_llm_api_key:
            return _format_search_results(search_results)
        
        llm = get_llm(temperature=0.3)
        
        # Format search results as context
        context = "\n\n".join([
            f"Source: {r['title']}\nURL: {r['url']}\n{r['content']}"
            for r in search_results
        ])
        
        system_prompt = """You are a helpful assistant that answers questions using web search results.
Synthesize the information from the search results to answer the user's question.
Always cite your sources by mentioning the website or URL.
If the search results don't contain relevant information, say so."""

        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Search Results:\n{context}\n\nQuestion: {query}"),
        ])
        
        return response.content.strip()
        
    except ImportError:
        return _format_search_results(search_results)
    except Exception as e:
        return f"Error generating response: {str(e)}"


def _format_search_results(results: list[dict[str, Any]]) -> str:
    """Format search results as a simple list."""
    if not results:
        return "No web search results found."
    
    formatted = "Here's what I found:\n\n"
    for i, r in enumerate(results[:5], 1):
        formatted += f"{i}. **{r['title']}**\n"
        formatted += f"   {r['content'][:200]}...\n"
        formatted += f"   Source: {r['url']}\n\n"
    
    return formatted


async def process_web_search_query(
    query: str,
    guild_id: int,  # Included for consistency but not used for filtering
) -> AskResponse:
    """
    Process a web search query and return formatted response.
    
    This is the main entry point for the Web Search agent.
    
    Args:
        query: Natural language query
        guild_id: Guild ID (for logging/tracking only)
        
    Returns:
        AskResponse with answer and sources
    """
    start_time = time.time()
    
    # Search the web
    results = await search_web(query)
    
    # Generate response
    answer = await generate_web_response(query, results)
    
    # Note: Web search doesn't return Discord MessageSource
    # but we include empty sources for API consistency
    
    execution_time = (time.time() - start_time) * 1000
    
    return AskResponse(
        answer=answer,
        sources=[],
        routed_to=RouterIntent.WEB_SEARCH,
        execution_time_ms=execution_time,
    )
