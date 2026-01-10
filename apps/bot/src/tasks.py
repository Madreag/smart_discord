"""
Celery Tasks for Message Processing

These tasks run outside the Discord event loop to avoid blocking.
The bot pushes tasks to Redis/Celery, workers process them asynchronously.

Features:
- Automatic retry with exponential backoff
- Priority queues (high, default, low)
- Dead letter queue for failed tasks

CONSTRAINT: Bot NEVER processes AI logic locally - always via Celery.
"""

import os
import sys
import json
from pathlib import Path
from typing import Optional
from datetime import datetime
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from celery import Celery
from celery.signals import task_failure
from packages.shared.python.models import IndexTaskPayload, DeleteTaskPayload

# Import production config
from apps.bot.src.celery_config import celery_app

# Dead letter queue name
DEAD_LETTER_QUEUE = "dead_letter"


def get_db_engine():
    """Get sync database engine."""
    from sqlalchemy import create_engine
    from apps.bot.src.config import get_bot_settings
    
    settings = get_bot_settings()
    sync_url = settings.database_url.replace("+asyncpg", "")
    return create_engine(sync_url, pool_pre_ping=True)


@celery_app.task(
    bind=True,
    name="index_messages",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
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
    
    # 5. Mark messages as indexed in PostgreSQL
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE messages 
            SET qdrant_point_id = :session_id, indexed_at = NOW()
            WHERE id = ANY(:message_ids)
        """), {"session_id": session_id, "message_ids": payload.message_ids})
        conn.commit()
    
    return {
        "status": "success",
        "guild_id": payload.guild_id,
        "channel_id": payload.channel_id,
        "session_id": session_id,
        "indexed_count": len(payload.message_ids),
    }


@celery_app.task(
    bind=True,
    name="delete_message_vector",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
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


@celery_app.task(
    bind=True,
    name="process_session",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
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
    
    # 5. Mark messages as indexed in PostgreSQL
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE messages 
            SET qdrant_point_id = :session_id, indexed_at = NOW()
            WHERE id = ANY(:message_ids)
        """), {"session_id": session_id, "message_ids": message_ids})
        conn.commit()
    
    return {
        "status": "success",
        "session_id": session_id,
        "guild_id": guild_id,
        "channel_id": channel_id,
        "message_count": len(message_ids),
    }


@celery_app.task(
    bind=True,
    name="ask_query",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
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


@celery_app.task(
    bind=True,
    name="batch_index_channel",
    time_limit=3600,  # 1 hour max
)
def batch_index_channel(
    self,
    guild_id: int,
    channel_id: int,
    channel_name: str,
    batch_size: int = 100,
) -> dict:
    """
    Batch index all unindexed messages in a channel.
    
    Runs in low-priority queue to not block real-time operations.
    """
    from sqlalchemy import text
    from apps.bot.src.sessionizer import sessionize_messages, Message
    
    print(f"[TASK] batch_index_channel: {channel_name}")
    
    engine = get_db_engine()
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, content, author_id, message_timestamp, reply_to_id
            FROM messages
            WHERE guild_id = :g AND channel_id = :c
              AND is_deleted = FALSE AND qdrant_point_id IS NULL
              AND content IS NOT NULL AND LENGTH(content) > 0
            ORDER BY message_timestamp
            LIMIT :limit
        """), {"g": guild_id, "c": channel_id, "limit": batch_size})
        rows = result.fetchall()
    
    if not rows:
        return {"status": "complete", "indexed": 0}
    
    # Sessionize
    messages = [Message(
        id=r.id,
        channel_id=channel_id,
        author_id=r.author_id,
        content=r.content,
        timestamp=r.message_timestamp,
        reply_to_id=r.reply_to_id,
    ) for r in rows]
    
    sessions = sessionize_messages(messages)
    
    # Queue each session
    queued = 0
    for session in sessions:
        if len(session.messages) >= 1:
            session_id = str(uuid4())
            process_session.apply_async(
                kwargs={
                    "guild_id": guild_id,
                    "channel_id": channel_id,
                    "channel_name": channel_name,
                    "message_ids": session.message_ids,
                    "start_time": session.start_time.isoformat(),
                    "end_time": session.end_time.isoformat(),
                },
                queue="default",
            )
            queued += 1
    
    return {
        "status": "processing",
        "messages_found": len(rows),
        "sessions_queued": queued,
    }


# Dead letter queue handler
@task_failure.connect
def handle_task_failure(sender=None, task_id=None, exception=None, args=None, kwargs=None, traceback=None, **kw):
    """
    Handle permanently failed tasks.
    
    Logs to dead letter queue for manual investigation.
    """
    import redis
    
    try:
        client = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
        
        failure_data = {
            "task_name": sender.name if sender else "unknown",
            "task_id": task_id,
            "args": args,
            "kwargs": kwargs,
            "exception": str(exception),
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Push to dead letter queue
        client.lpush(DEAD_LETTER_QUEUE, json.dumps(failure_data))
        
        print(f"[DLQ] Task {task_id} failed permanently: {exception}")
    except Exception as e:
        print(f"[DLQ] Failed to log to dead letter queue: {e}")


@celery_app.task(name="get_queue_stats")
def get_queue_stats() -> dict:
    """Get queue statistics for monitoring."""
    import redis
    
    client = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
    
    queues = ["high", "default", "low", DEAD_LETTER_QUEUE]
    stats = {}
    
    for queue in queues:
        stats[queue] = client.llen(queue)
    
    return stats


@celery_app.task(name="process_dead_letter")
def process_dead_letter(limit: int = 10) -> dict:
    """
    Process items from dead letter queue.
    
    Can be used to retry or investigate failures.
    """
    import redis
    
    client = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
    
    processed = []
    for _ in range(limit):
        item = client.rpop(DEAD_LETTER_QUEUE)
        if not item:
            break
        processed.append(json.loads(item))
    
    return {
        "processed_count": len(processed),
        "items": processed,
    }


@celery_app.task(
    bind=True,
    name="process_attachment",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
    time_limit=300,  # 5 min max for large files
)
def process_attachment(self, payload_dict: dict) -> dict:
    """
    Process a Discord attachment (PDF, Image, TXT, MD).
    
    CRITICAL: File download happens HERE in the API worker, NOT in the bot.
    This prevents blocking the Discord Gateway.
    
    Pipeline:
    1. Download file from Discord CDN
    2. Extract text (PDF/TXT) or generate description (Image)
    3. Chunk content
    4. Embed and store in Qdrant with source_type tagging
    5. Update Postgres with processing status
    """
    import asyncio
    from sqlalchemy import text
    
    attachment_id = payload_dict.get("attachment_id")
    guild_id = payload_dict.get("guild_id")
    channel_id = payload_dict.get("channel_id")
    url = payload_dict.get("url")
    filename = payload_dict.get("filename")
    
    print(f"[TASK] process_attachment: {filename}")
    
    engine = get_db_engine()
    
    try:
        # Update status to processing
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE attachments 
                SET processing_status = 'processing', updated_at = NOW()
                WHERE id = :id
            """), {"id": attachment_id})
            conn.commit()
        
        # Import document processor
        from apps.api.src.services.document_processor import (
            DocumentProcessor,
            AttachmentPayload,
        )
        
        processor = DocumentProcessor()
        
        # Create payload
        payload = AttachmentPayload(
            attachment_id=attachment_id,
            message_id=payload_dict.get("message_id", attachment_id),
            guild_id=guild_id,
            channel_id=channel_id,
            url=url,
            proxy_url=payload_dict.get("proxy_url"),
            filename=filename,
            content_type=payload_dict.get("content_type"),
            size_bytes=payload_dict.get("size_bytes", 0),
        )
        
        # Process the attachment (async call in sync context)
        result = asyncio.get_event_loop().run_until_complete(
            processor.process_attachment(payload)
        )
        
        if not result.success:
            # Update status to failed
            with engine.connect() as conn:
                conn.execute(text("""
                    UPDATE attachments 
                    SET processing_status = 'failed', 
                        processing_error = :error,
                        updated_at = NOW()
                    WHERE id = :id
                """), {"id": attachment_id, "error": result.error})
                conn.commit()
            
            return {
                "status": "failed",
                "attachment_id": attachment_id,
                "error": result.error,
            }
        
        # Store extracted content and chunks
        chunk_ids = []
        
        with engine.connect() as conn:
            # Update attachment with extracted content
            conn.execute(text("""
                UPDATE attachments 
                SET processing_status = 'completed',
                    extracted_text = :text,
                    description = :description,
                    processed_at = NOW(),
                    chunk_count = :chunk_count,
                    updated_at = NOW()
                WHERE id = :id
            """), {
                "id": attachment_id,
                "text": result.extracted_text,
                "description": result.description,
                "chunk_count": len(result.chunks),
            })
            
            # Insert document chunks
            for chunk in result.chunks:
                chunk_id = str(uuid4())
                conn.execute(text("""
                    INSERT INTO document_chunks (id, attachment_id, guild_id, chunk_index,
                                                  chunk_text, chunk_type, heading_context, created_at)
                    VALUES (:id, :attachment_id, :guild_id, :chunk_index,
                            :chunk_text, :chunk_type, :heading_context, NOW())
                """), {
                    "id": chunk_id,
                    "attachment_id": attachment_id,
                    "guild_id": guild_id,
                    "chunk_index": chunk.chunk_index,
                    "chunk_text": chunk.text,
                    "chunk_type": chunk.chunk_type,
                    "heading_context": chunk.heading_context,
                })
                chunk_ids.append(chunk_id)
            
            conn.commit()
        
        # Embed chunks to Qdrant
        if result.chunks:
            _embed_document_chunks(
                attachment_id=attachment_id,
                guild_id=guild_id,
                channel_id=channel_id,
                filename=filename,
                source_type=result.source_type.value,
                chunks=result.chunks,
                chunk_ids=chunk_ids,
            )
        
        return {
            "status": "success",
            "attachment_id": attachment_id,
            "filename": filename,
            "source_type": result.source_type.value,
            "chunks_created": len(result.chunks),
        }
        
    except Exception as e:
        # Update status to failed
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE attachments 
                SET processing_status = 'failed', 
                    processing_error = :error,
                    updated_at = NOW()
                WHERE id = :id
            """), {"id": attachment_id, "error": str(e)})
            conn.commit()
        
        raise  # Re-raise for Celery retry


@celery_app.task(
    bind=True,
    name="delete_attachment_vectors",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def delete_attachment_vectors(self, payload_dict: dict) -> dict:
    """
    Delete attachment vectors from Qdrant (Right to be Forgotten).
    
    Called when a message with attachments is deleted.
    Must hard-delete all document chunks from Qdrant.
    """
    from apps.api.src.services.qdrant_service import qdrant_service
    
    attachment_id = payload_dict.get("attachment_id")
    guild_id = payload_dict.get("guild_id")
    qdrant_point_ids = payload_dict.get("qdrant_point_ids", [])
    
    print(f"[TASK] delete_attachment_vectors: attachment {attachment_id}, {len(qdrant_point_ids)} points")
    
    deleted_count = 0
    for point_id in qdrant_point_ids:
        try:
            success = qdrant_service.delete_by_session_id(point_id)
            if success:
                deleted_count += 1
        except Exception as e:
            print(f"[ERROR] Failed to delete point {point_id}: {e}")
    
    return {
        "status": "success",
        "attachment_id": attachment_id,
        "deleted_count": deleted_count,
        "total_points": len(qdrant_point_ids),
    }


def _embed_document_chunks(
    attachment_id: int,
    guild_id: int,
    channel_id: int,
    filename: str,
    source_type: str,
    chunks: list,
    chunk_ids: list[str],
) -> None:
    """
    Embed document chunks to Qdrant with source_type tagging.
    
    Tags chunks with metadata for filtering (e.g., "Search only PDFs").
    """
    from sqlalchemy import text
    from apps.api.src.services.qdrant_service import qdrant_service
    
    engine = get_db_engine()
    qdrant_point_ids = []
    
    for chunk, chunk_id in zip(chunks, chunk_ids):
        try:
            # Create embedding using factory (respects LOCAL/OPENAI config)
            from apps.api.src.core.llm_factory import get_embedding_model
            
            embedding_model = get_embedding_model()
            vector = embedding_model.embed_query(chunk.text)
            
            # Upsert to Qdrant with document metadata
            point_id = chunk_id
            qdrant_service.upsert_with_metadata(
                point_id=point_id,
                vector=vector,
                payload={
                    "guild_id": guild_id,
                    "channel_id": channel_id,
                    "source_type": source_type,  # 'document', 'pdf', 'image', etc.
                    "type": "document",  # Distinguishes from 'chat' sessions
                    "parent_file": filename,
                    "attachment_id": attachment_id,
                    "chunk_index": chunk.chunk_index,
                    "chunk_type": chunk.chunk_type,
                    "heading_context": chunk.heading_context,
                    "text": chunk.text[:1000],  # Store preview
                },
            )
            
            qdrant_point_ids.append(point_id)
            
            # Update chunk with qdrant_point_id
            with engine.connect() as conn:
                conn.execute(text("""
                    UPDATE document_chunks 
                    SET qdrant_point_id = :point_id, indexed_at = NOW()
                    WHERE id = :id
                """), {"id": chunk_id, "point_id": point_id})
                conn.commit()
                
        except Exception as e:
            print(f"[ERROR] Failed to embed chunk {chunk_id}: {e}")
    
    # Update attachment with qdrant_point_ids
    if qdrant_point_ids:
        import uuid as uuid_module
        # Convert string UUIDs to proper UUID objects for psycopg2
        uuid_list = [uuid_module.UUID(pid) for pid in qdrant_point_ids]
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE attachments 
                SET qdrant_point_ids = :point_ids, 
                    indexed_at = NOW()
                WHERE id = :id
            """), {"id": attachment_id, "point_ids": uuid_list})
            conn.commit()
