"""
Hybrid Sessionizer - Time-based first, then semantic refinement.

Strategy:
1. First pass: Split by time gaps (existing sessionizer)
2. Second pass: For large sessions, apply semantic splitting

This provides the best balance of speed and accuracy.
"""

from typing import Optional
from datetime import datetime

from apps.bot.src.sessionizer import sessionize_messages, Message, Session


def hybrid_sessionize(
    messages: list[Message],
    time_gap_minutes: int = 15,
    semantic_threshold: float = 90,
    semantic_split_threshold: int = 15,
    min_session_size: int = 2,
    max_session_size: int = 30,
) -> list[Session]:
    """
    Hybrid approach: time-based first, then semantic refinement.
    
    Args:
        messages: List of Message objects
        time_gap_minutes: Time gap threshold for first pass
        semantic_threshold: Percentile threshold for semantic splitting
        semantic_split_threshold: Min session size to trigger semantic splitting
        min_session_size: Minimum messages per final session
        max_session_size: Maximum messages per final session
        
    Returns:
        List of Session objects with semantic awareness
    """
    if not messages:
        return []
    
    # First pass: time-based sessionization
    time_sessions = sessionize_messages(messages)
    
    final_sessions = []
    
    for session in time_sessions:
        if len(session.messages) < semantic_split_threshold:
            # Small session - keep as is if meets minimum
            if len(session.messages) >= min_session_size:
                final_sessions.append(session)
        else:
            # Large session - apply semantic splitting
            semantic_sessions = _apply_semantic_splitting(
                session,
                threshold=semantic_threshold,
                min_size=min_session_size,
                max_size=max_session_size,
            )
            final_sessions.extend(semantic_sessions)
    
    return final_sessions


def _apply_semantic_splitting(
    session: Session,
    threshold: float = 90,
    min_size: int = 2,
    max_size: int = 30,
) -> list[Session]:
    """
    Apply semantic chunking to a large session.
    
    Returns list of smaller, semantically coherent sessions.
    """
    try:
        from apps.api.src.services.semantic_chunker import semantic_chunk_messages
        
        # Convert messages to dicts for semantic chunker
        msg_dicts = [
            {
                "id": m.id,
                "content": m.content,
                "author_id": m.author_id,
                "timestamp": m.timestamp,
                "channel_id": m.channel_id,
                "reply_to_id": m.reply_to_id,
            }
            for m in session.messages
        ]
        
        # Apply semantic chunking
        chunks = semantic_chunk_messages(
            msg_dicts,
            method="percentile",
            threshold=threshold,
            min_chunk_size=min_size,
            max_chunk_size=max_size,
        )
        
        # Convert chunks back to Session objects
        result_sessions = []
        for chunk in chunks:
            if len(chunk.messages) >= min_size:
                new_session = Session(channel_id=session.channel_id)
                for msg_dict in chunk.messages:
                    new_session.add_message(Message(
                        id=msg_dict["id"],
                        channel_id=msg_dict.get("channel_id", session.channel_id),
                        author_id=msg_dict["author_id"],
                        content=msg_dict["content"],
                        timestamp=msg_dict["timestamp"],
                        reply_to_id=msg_dict.get("reply_to_id"),
                    ))
                result_sessions.append(new_session)
        
        return result_sessions if result_sessions else [session]
        
    except Exception as e:
        # Fallback: split by max_size only
        return _split_by_size(session, min_size, max_size)


def _split_by_size(
    session: Session,
    min_size: int,
    max_size: int,
) -> list[Session]:
    """Fallback: split session by size only."""
    if len(session.messages) <= max_size:
        return [session] if len(session.messages) >= min_size else []
    
    result = []
    for i in range(0, len(session.messages), max_size):
        chunk = session.messages[i:i + max_size]
        if len(chunk) >= min_size:
            new_session = Session(channel_id=session.channel_id)
            new_session.messages = chunk
            result.append(new_session)
    
    return result
