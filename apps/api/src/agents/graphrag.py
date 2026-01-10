"""
GraphRAG Agent - Handles thematic queries using topic clustering.

Answers broad questions like "What are the main topics people discuss?"
Uses the lightweight thematic analyzer for fast, local processing.
"""

import time
from typing import Optional

from packages.shared.python.models import AskResponse, MessageSource, RouterIntent
from apps.api.src.services.thematic_analyzer import get_thematic_analyzer


async def process_graphrag_query(
    query: str,
    guild_id: int,
) -> AskResponse:
    """
    Process a thematic/broad query using topic clustering.
    
    Args:
        query: Broad question like "What are the main topics?"
        guild_id: Guild ID
        
    Returns:
        AskResponse with synthesized answer from topic clusters
    """
    start_time = time.time()
    
    analyzer = get_thematic_analyzer(guild_id)
    
    # Try to answer using cached topic clusters
    answer = await analyzer.answer_thematic_query(query)
    
    execution_time = (time.time() - start_time) * 1000
    
    return AskResponse(
        answer=answer,
        sources=[],  # GraphRAG doesn't have specific message sources
        routed_to=RouterIntent.GRAPH_RAG,
        execution_time_ms=execution_time,
    )
