"""
General Knowledge Agent: Direct LLM Response for Factual Questions

Handles factual questions that don't require Discord data or web search,
using the LLM's training knowledge to provide answers.
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
        
        system_prompt = f"""You are a helpful Discord bot assistant that answers questions clearly and concisely.

IMPORTANT: You have access to the current date and time. When asked about the time, date, or day, USE THIS INFORMATION:
Current date and time: {current_time}

For time-related questions, provide the answer using the timestamp above. Convert to the user's likely timezone if they mention one, otherwise give UTC time.

For factual questions, provide accurate answers based on your knowledge. If you're genuinely uncertain about something, say so."""

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
