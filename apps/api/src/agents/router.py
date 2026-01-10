"""
Router Agent: Intent Classification for Query Routing

Routes user queries to the appropriate processing pipeline:
- analytics_db: Statistical/aggregate queries → Text-to-SQL
- vector_rag: Semantic/content queries → Vector search + RAG
- web_search: External information queries → Web search API

Uses a lightweight classifier that can work without LLM for common patterns,
falling back to LLM classification for ambiguous queries.
"""

import re
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from packages.shared.python.models import RouterIntent


# Pattern-based classification for common query types
# These patterns are checked first for fast, deterministic routing

# Discord-related terms that indicate analytics queries about server data
DISCORD_TERMS = r"(messages?|users?|members?|channels?|server|guild|activity|sent|posted|active)"

ANALYTICS_PATTERNS: list[re.Pattern[str]] = [
    # Counting/aggregation - MUST mention Discord-related terms
    re.compile(rf"\b(how many|count|total|number of)\b.*\b{DISCORD_TERMS}\b", re.IGNORECASE),
    re.compile(rf"\b{DISCORD_TERMS}\b.*\b(how many|count|total|number of)\b", re.IGNORECASE),
    # Ranking/comparison
    re.compile(r"\b(who spoke|most active|least active|top \d+|bottom \d+)\b", re.IGNORECASE),
    re.compile(r"\b(most|least|highest|lowest|average|avg|sum|min|max)\b.*\b(messages?|users?|channels?)\b", re.IGNORECASE),
    # Time-based statistics - MUST mention Discord-related terms
    re.compile(r"\b(messages?|activity)\b.*\b(per|by|each)\b.*\b(day|week|month|hour|user|channel)\b", re.IGNORECASE),
    re.compile(rf"\b(between|from|since|until|last)\b.*\b(am|pm|\d{{1,2}}:\d{{2}}|week|month|day)\b.*\b{DISCORD_TERMS}\b", re.IGNORECASE),
    # Explicit data queries
    re.compile(r"\b(show|list|display|get)\b.*\b(count|stats|statistics|metrics)\b", re.IGNORECASE),
    re.compile(r"\b(message counts?|user counts?|channel stats?)\b", re.IGNORECASE),
]

VECTOR_RAG_PATTERNS: list[re.Pattern[str]] = [
    # Content/topic queries
    re.compile(r"\b(what (was|were|is|are)|summarize|summary of)\b.*\b(said|discussed|talked|mentioned)\b", re.IGNORECASE),
    re.compile(r"\b(summarize|summary of)\b.*\b(discussion|conversation|chat|thread)\b", re.IGNORECASE),
    re.compile(r"\b(find|search|look for)\b.*\b(messages?|discussions?|conversations?)\b.*\b(about|where|that)\b", re.IGNORECASE),
    re.compile(r"\b(main|common|frequent)\b.*\b(complaints?|issues?|topics?|themes?|concerns?)\b", re.IGNORECASE),
    # Semantic understanding
    re.compile(r"\b(what (do|does) .* think|opinions? (on|about)|sentiment)\b", re.IGNORECASE),
    re.compile(r"\b(explain|describe|tell me about)\b.*\b(discussion|conversation|thread)\b", re.IGNORECASE),
    # Content retrieval
    re.compile(r"\b(what has been said|what did .* say)\b", re.IGNORECASE),
]

GRAPH_RAG_PATTERNS: list[re.Pattern[str]] = [
    # Thematic/broad queries about topics and trends
    re.compile(r"\b(main|common|frequent|popular|major)\b.*\b(topics?|themes?|subjects?|discussions?)\b", re.IGNORECASE),
    re.compile(r"\bwhat (do|does) (everyone|people|users?|members?) (talk|discuss|chat) about\b", re.IGNORECASE),
    re.compile(r"\b(summarize|overview|summary of)\b.*\b(server|community|all)\b", re.IGNORECASE),
    re.compile(r"\b(general|overall|common)\b.*\b(sentiment|opinion|feeling|mood)\b", re.IGNORECASE),
    re.compile(r"\b(trends?|patterns?|themes?)\b.*\b(in|across|throughout)\b.*\b(server|community|channels?)\b", re.IGNORECASE),
    # Big-picture questions
    re.compile(r"\bwhat are the\b.*\b(main|biggest|most common|top)\b.*\b(complaints?|issues?|concerns?|problems?)\b", re.IGNORECASE),
    re.compile(r"\b(analyze|analysis of)\b.*\b(conversations?|discussions?|community)\b", re.IGNORECASE),
]

WEB_SEARCH_PATTERNS: list[re.Pattern[str]] = [
    # External/current information
    re.compile(r"\b(latest|current|recent|today'?s?)\b.*\b(news|price|version|release)\b", re.IGNORECASE),
    re.compile(r"\b(how (do|does|to|can)|what is the .* way to)\b.*\b(configure|setup|install|use)\b", re.IGNORECASE),
    # Explicit external reference
    re.compile(r"\b(according to|based on|from the web|google|search for)\b", re.IGNORECASE),
    # Technology/tool questions (likely need docs)
    re.compile(r"\b(nginx|docker|kubernetes|aws|gcp|azure)\b.*\b(how|configure|setup)\b", re.IGNORECASE),
    # Price/market data
    re.compile(r"\b(price of|cost of|worth of)\b.*\b(bitcoin|eth|stock|crypto)\b", re.IGNORECASE),
]


def _classify_by_pattern(query: str) -> Optional[RouterIntent]:
    """
    Attempt to classify query using regex patterns.
    
    Returns None if no pattern matches (requires LLM fallback).
    """
    # Check analytics patterns first (most specific)
    for pattern in ANALYTICS_PATTERNS:
        if pattern.search(query):
            return RouterIntent.ANALYTICS_DB
    
    # Check graph RAG patterns (thematic/broad queries)
    for pattern in GRAPH_RAG_PATTERNS:
        if pattern.search(query):
            return RouterIntent.GRAPH_RAG
    
    # Check web search patterns (external info)
    for pattern in WEB_SEARCH_PATTERNS:
        if pattern.search(query):
            return RouterIntent.WEB_SEARCH
    
    # Check vector RAG patterns
    for pattern in VECTOR_RAG_PATTERNS:
        if pattern.search(query):
            return RouterIntent.VECTOR_RAG
    
    return None


async def _classify_with_llm(query: str) -> RouterIntent:
    """
    Use LLM to classify ambiguous queries.
    
    Falls back to GENERAL_KNOWLEDGE if LLM is unavailable (safe default for unknown queries).
    """
    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        
        from apps.api.src.core.config import get_settings
        from apps.api.src.core.llm_factory import get_llm
        
        settings = get_settings()
        if not settings.active_llm_api_key:
            # No API key - default to general knowledge (direct LLM answer)
            return RouterIntent.GENERAL_KNOWLEDGE
        
        llm = get_llm(temperature=0.0)
        
        system_prompt = """You are a query intent classifier for a Discord community analytics system.
Classify the user's query into exactly ONE of these categories:

- analytics_db: Statistical queries about THIS SERVER's message counts, user activity, rankings, time-based metrics.
  Examples: "Who sent the most messages?", "How many messages last week?", "Most active channel?"
  
- vector_rag: Semantic content queries about what was discussed, finding specific discussions or what someone said.
  Examples: "Summarize the React discussion", "What did John say about the bug?", "Find messages about authentication"
  
- graph_rag: Broad thematic queries about overall topics, trends, or patterns across the ENTIRE server.
  Examples: "What are the main topics people discuss?", "What are common complaints?", "Overview of server discussions"
  
- web_search: Queries requiring external/current information that needs real-time web search.
  Examples: "Latest Python version?", "Current Bitcoin price?", "Today's news?"

- general_knowledge: Factual questions that can be answered from general knowledge, NOT about Discord server data.
  Examples: "How many states are in the US?", "What is the capital of France?", "Who wrote Romeo and Juliet?"

Respond with ONLY the category name, nothing else."""

        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=query),
        ])
        
        intent_str = response.content.strip().lower()
        
        if "analytics" in intent_str:
            return RouterIntent.ANALYTICS_DB
        elif "graph" in intent_str:
            return RouterIntent.GRAPH_RAG
        elif "web" in intent_str:
            return RouterIntent.WEB_SEARCH
        elif "general" in intent_str:
            return RouterIntent.GENERAL_KNOWLEDGE
        else:
            return RouterIntent.VECTOR_RAG
            
    except ImportError:
        # LangChain not available - default to general knowledge
        return RouterIntent.GENERAL_KNOWLEDGE
    except Exception:
        # Any other error - default to general knowledge
        return RouterIntent.GENERAL_KNOWLEDGE


async def classify_intent(query: str) -> RouterIntent:
    """
    Classify the intent of a user query for routing.
    
    Uses pattern matching first for speed and determinism,
    falls back to LLM for ambiguous queries.
    
    Args:
        query: The user's natural language query
        
    Returns:
        RouterIntent enum indicating where to route the query
    """
    # Try pattern-based classification first (fast, deterministic)
    pattern_result = _classify_by_pattern(query)
    if pattern_result is not None:
        return pattern_result
    
    # Fall back to LLM classification for ambiguous queries
    return await _classify_with_llm(query)
