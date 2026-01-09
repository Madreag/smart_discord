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


def get_db_engine():
    """Get sync database engine."""
    from sqlalchemy import create_engine
    from apps.bot.src.config import get_bot_settings
    
    settings = get_bot_settings()
    sync_url = settings.database_url.replace("+asyncpg", "")
    return create_engine(sync_url, pool_pre_ping=True)


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
    from sqlalchemy import text
    from apps.api.src.core.llm_factory import get_embedding_model
    from apps.api.src.services.qdrant_service import qdrant_service
    from apps.api.src.services.enrichment_service import enrich_session
    
    payload = IndexTaskPayload(**payload_dict)
    engine = get_db_engine()
    
    # 1. Fetch messages from Postgres
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT m.id, m.content, m.message_timestamp, u.username, u.global_name
            FROM messages m
            JOIN users u ON m.author_id = u.id
            WHERE m.id = ANY(:message_ids)
              AND m.guild_id = :guild_id
              AND m.is_deleted = FALSE
            ORDER BY m.message_timestamp ASC
        """), {"message_ids": payload.message_ids, "guild_id": payload.guild_id})
        
        rows = result.fetchall()
    
    if not rows:
        return {"status": "skipped", "reason": "no_messages_found"}
    
    # 2. Enrich messages with metadata
    messages = [
        {
            "content": row.content,
            "author_name": row.global_name or row.username,
            "timestamp": row.message_timestamp,
        }
        for row in rows
    ]
    
    enriched_text = enrich_session(messages, channel_name=payload.channel_name)
    
    # 3. Generate embedding
    embedding_model = get_embedding_model()
    embedding = embedding_model.embed_query(enriched_text)
    
    # 4. Upsert to Qdrant
    session_id = str(uuid4())
    success = qdrant_service.upsert_session(
        session_id=session_id,
        guild_id=payload.guild_id,
        channel_id=payload.channel_id,
        embedding=embedding,
        message_ids=payload.message_ids,
        content_preview=enriched_text[:500],
        start_time=payload.start_time or datetime.utcnow().isoformat(),
        end_time=payload.end_time or datetime.utcnow().isoformat(),
    )
    
    if not success:
        raise Exception("Qdrant upsert failed")
    
    return {
        "status": "success",
        "guild_id": payload.guild_id,
        "channel_id": payload.channel_id,
        "session_id": session_id,
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
    from apps.api.src.services.qdrant_service import qdrant_service
    
    payload = DeleteTaskPayload(**payload_dict)
    
    # Delete vector from Qdrant by point_id if provided
    if payload.qdrant_point_id:
        success = qdrant_service.delete_by_session_id(payload.qdrant_point_id)
        return {
            "status": "success" if success else "not_found",
            "guild_id": payload.guild_id,
            "message_id": payload.message_id,
            "deleted_point_id": payload.qdrant_point_id,
        }
    
    return {
        "status": "skipped",
        "guild_id": payload.guild_id,
        "message_id": payload.message_id,
        "reason": "no_qdrant_point_id",
    }


@celery_app.task(bind=True, name="process_session")
def process_session(
    self,
    guild_id: int,
    channel_id: int,
    channel_name: str,
    message_ids: list[int],
    start_time: str,
    end_time: str,
) -> dict:
    """
    Process a message session - fetch, embed, and store in Qdrant.
    
    Args:
        guild_id: Guild ID
        channel_id: Channel ID
        channel_name: Channel name for context
        message_ids: List of message IDs in session
        start_time: Session start timestamp (ISO format)
        end_time: Session end timestamp (ISO format)
        
    Returns:
        Result dict with session info
    """
    from sqlalchemy import text
    from apps.api.src.core.llm_factory import get_embedding_model
    from apps.api.src.services.qdrant_service import qdrant_service
    from apps.api.src.services.enrichment_service import enrich_session
    
    session_id = str(uuid4())
    engine = get_db_engine()
    
    # 1. Fetch messages from Postgres
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT m.id, m.content, m.message_timestamp, m.author_id,
                   u.username, u.global_name
            FROM messages m
            JOIN users u ON m.author_id = u.id
            WHERE m.id = ANY(:message_ids)
              AND m.guild_id = :guild_id
              AND m.is_deleted = FALSE
            ORDER BY m.message_timestamp ASC
        """), {"message_ids": message_ids, "guild_id": guild_id})
        
        rows = result.fetchall()
    
    if not rows:
        return {"status": "skipped", "reason": "no_messages_found"}
    
    # 2. Enrich messages with metadata
    messages = [
        {
            "content": row.content,
            "author_name": row.global_name or row.username,
            "timestamp": row.message_timestamp,
        }
        for row in rows
    ]
    author_ids = list(set(row.author_id for row in rows))
    
    enriched_text = enrich_session(messages, channel_name=channel_name)
    
    # 3. Generate embedding
    embedding_model = get_embedding_model()
    embedding = embedding_model.embed_query(enriched_text)
    
    # 4. Upsert to Qdrant
    success = qdrant_service.upsert_session(
        session_id=session_id,
        guild_id=guild_id,
        channel_id=channel_id,
        embedding=embedding,
        message_ids=message_ids,
        content_preview=enriched_text[:500],
        start_time=start_time,
        end_time=end_time,
        author_ids=author_ids,
    )
    
    if not success:
        raise Exception("Qdrant upsert failed")
    
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
