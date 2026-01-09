"""
Celery Tasks for Message Processing

These tasks run outside the Discord event loop to avoid blocking.
The bot pushes tasks to Redis/Celery, workers process them asynchronously.

CONSTRAINT: Bot NEVER processes AI logic locally - always via Celery.
"""

import sys
from pathlib import Path
from typing import Optional
from datetime import datetime
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from celery import Celery
from packages.shared.python.models import IndexTaskPayload, DeleteTaskPayload

# Initialize Celery app
celery_app = Celery(
    "smart_discord",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/1",
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minute timeout
    worker_prefetch_multiplier=1,
)


@celery_app.task(bind=True, name="index_messages")
def index_messages(self, payload_dict: dict) -> dict:
    """
    Index messages to Qdrant after storing in PostgreSQL.
    
    CONSTRAINT: Cannot write to Qdrant without Postgres record.
    
    Args:
        payload_dict: IndexTaskPayload as dict
        
    Returns:
        Result dict with indexed message IDs
    """
    payload = IndexTaskPayload(**payload_dict)
    
    # TODO: Implement actual indexing logic
    # 1. Verify messages exist in Postgres
    # 2. Generate embeddings
    # 3. Upsert to Qdrant with guild_id in payload
    # 4. Update qdrant_point_id in Postgres
    
    return {
        "status": "success",
        "guild_id": payload.guild_id,
        "channel_id": payload.channel_id,
        "indexed_count": len(payload.message_ids),
    }


@celery_app.task(bind=True, name="delete_message_vector")
def delete_message_vector(self, payload_dict: dict) -> dict:
    """
    Delete message vector from Qdrant (Right to be Forgotten).
    
    CONSTRAINT: Called when on_message_delete fires.
    Must hard-delete from Qdrant after soft-delete in Postgres.
    
    Args:
        payload_dict: DeleteTaskPayload as dict
        
    Returns:
        Result dict with deletion status
    """
    payload = DeleteTaskPayload(**payload_dict)
    
    # TODO: Implement actual deletion logic
    # 1. Verify message is soft-deleted in Postgres
    # 2. Delete vector from Qdrant by point_id
    # 3. Clear qdrant_point_id in Postgres
    
    return {
        "status": "success",
        "guild_id": payload.guild_id,
        "message_id": payload.message_id,
        "deleted_point_id": payload.qdrant_point_id,
    }


@celery_app.task(bind=True, name="process_session")
def process_session(
    self,
    guild_id: int,
    channel_id: int,
    message_ids: list[int],
    start_time: str,
    end_time: str,
) -> dict:
    """
    Process a message session using the Sliding Window Sessionizer.
    
    Groups messages by:
    - Same channel_id
    - Time difference < 15 minutes
    - No topic shifts or reply chain breaks
    
    Args:
        guild_id: Guild ID
        channel_id: Channel ID
        message_ids: List of message IDs in session
        start_time: Session start timestamp (ISO format)
        end_time: Session end timestamp (ISO format)
        
    Returns:
        Result dict with session info
    """
    session_id = str(uuid4())
    
    # TODO: Implement actual session processing
    # 1. Fetch message content from Postgres
    # 2. Concatenate into session text
    # 3. Generate embedding
    # 4. Create summary using LLM
    # 5. Insert session record in Postgres
    # 6. Upsert session vector to Qdrant
    
    return {
        "status": "success",
        "session_id": session_id,
        "guild_id": guild_id,
        "channel_id": channel_id,
        "message_count": len(message_ids),
    }


@celery_app.task(bind=True, name="ask_query")
def ask_query(
    self,
    guild_id: int,
    query: str,
    channel_ids: Optional[list[int]] = None,
) -> dict:
    """
    Process an /ai ask query via the Cognitive Layer API.
    
    This is called by the bot after deferring the interaction response.
    
    Args:
        guild_id: Guild ID for multi-tenant filtering
        query: User's natural language query
        channel_ids: Optional channel filter
        
    Returns:
        Result dict with answer and sources
    """
    import httpx
    
    # Call the Cognitive Layer API
    try:
        response = httpx.post(
            "http://localhost:8000/ask",
            json={
                "guild_id": guild_id,
                "query": query,
                "channel_ids": channel_ids,
            },
            timeout=60.0,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "answer": f"Error processing query: {str(e)}",
            "sources": [],
            "routed_to": "unknown",
            "execution_time_ms": 0,
        }
