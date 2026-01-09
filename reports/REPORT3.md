# REPORT 3: Discord Message Edit & Delete Event Handlers

> **Priority**: P0 (Critical)  
> **Effort**: 3-4 hours  
> **Status**: Partial (delete exists, edit missing)

---

## 1. Executive Summary

The bot handles `on_message_delete` but the implementation is incomplete (TODO placeholders). The `on_message_edit` handler is completely missing. This means:

- Edited messages have stale vectors in Qdrant
- Deleted messages may still appear in RAG results
- "Right to be Forgotten" compliance is broken

**Target State**: Full event handling for edits and deletes with Postgres + Qdrant sync.

---

## 2. Current Implementation Analysis

### What Exists

```python
# apps/bot/src/bot.py (current)
@bot.event
async def on_message_delete(message: discord.Message) -> None:
    if not message.guild:
        return
    
    # TODO: Get qdrant_point_id from Postgres
    qdrant_point_id = None  # <-- Always None!
    
    if qdrant_point_id:  # <-- Never executes
        payload = DeleteTaskPayload(...)
        delete_message_vector.delay(payload.model_dump())
```

### What's Missing

1. **`on_message_edit` handler** - Doesn't exist
2. **`on_raw_message_edit` handler** - For uncached messages
3. **`on_raw_message_delete` handler** - For uncached messages
4. **Postgres lookup** - Get `qdrant_point_id` before deletion
5. **Actual Qdrant deletion** - Currently a no-op

---

## 3. Discord.py Event System Deep Dive

### Cached vs Raw Events

| Event | When Fired | Has Full Message? |
|-------|------------|-------------------|
| `on_message_edit` | Message in cache | Yes |
| `on_raw_message_edit` | Always | Only if cached |
| `on_message_delete` | Message in cache | Yes |
| `on_raw_message_delete` | Always | Only if cached |

**Best Practice**: Use `on_raw_*` events for reliability - they fire even if the message wasn't cached.

### Message Cache Behavior

```python
# Discord.py caches ~1000 messages per channel by default
# Messages older than this won't trigger on_message_edit/delete

# To handle ALL edits/deletes, use raw events:
@bot.event
async def on_raw_message_edit(payload: discord.RawMessageUpdateEvent):
    # payload.message_id - always available
    # payload.cached_message - only if was in cache
    # payload.data - raw Discord API data
    pass
```

---

## 4. Implementation Guide

### Step 1: Complete Delete Handler

```python
# apps/bot/src/bot.py

@bot.event
async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent) -> None:
    """
    Handle message deletion (Right to be Forgotten).
    
    Uses raw event to catch ALL deletions, not just cached messages.
    
    Pipeline:
    1. Soft delete in Postgres (preserve stats)
    2. Hard delete from Qdrant (privacy)
    """
    # Skip DMs
    if not payload.guild_id:
        return
    
    message_id = payload.message_id
    guild_id = payload.guild_id
    
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            # Step 1: Soft delete in Postgres and get qdrant info
            result = conn.execute(text("""
                UPDATE messages 
                SET 
                    is_deleted = TRUE,
                    deleted_at = NOW(),
                    content = '[deleted]'
                WHERE id = :message_id 
                  AND guild_id = :guild_id
                RETURNING qdrant_point_id
            """), {
                "message_id": message_id,
                "guild_id": guild_id,
            })
            
            row = result.fetchone()
            conn.commit()
            
            # Step 2: Queue Qdrant deletion if message was indexed
            if row and row.qdrant_point_id:
                from apps.bot.src.tasks import delete_message_vectors
                delete_message_vectors.delay(
                    guild_id=guild_id,
                    message_ids=[message_id],
                )
                print(f"[DELETE] Queued Qdrant deletion for message {message_id}")
            else:
                print(f"[DELETE] Message {message_id} not indexed, skipping Qdrant")
                
    except Exception as e:
        print(f"[ERROR] on_raw_message_delete: {e}")


@bot.event
async def on_raw_bulk_message_delete(payload: discord.RawBulkMessageDeleteEvent) -> None:
    """
    Handle bulk message deletion (e.g., channel purge).
    
    More efficient than handling each message individually.
    """
    if not payload.guild_id:
        return
    
    message_ids = list(payload.message_ids)
    guild_id = payload.guild_id
    
    if not message_ids:
        return
    
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            # Bulk soft delete in Postgres
            result = conn.execute(text("""
                UPDATE messages 
                SET 
                    is_deleted = TRUE,
                    deleted_at = NOW(),
                    content = '[deleted]'
                WHERE id = ANY(:message_ids)
                  AND guild_id = :guild_id
                RETURNING id, qdrant_point_id
            """), {
                "message_ids": message_ids,
                "guild_id": guild_id,
            })
            
            rows = result.fetchall()
            conn.commit()
            
            # Get IDs of indexed messages
            indexed_ids = [row.id for row in rows if row.qdrant_point_id]
            
            if indexed_ids:
                from apps.bot.src.tasks import delete_message_vectors
                delete_message_vectors.delay(
                    guild_id=guild_id,
                    message_ids=indexed_ids,
                )
                print(f"[BULK DELETE] Queued {len(indexed_ids)} messages for Qdrant deletion")
                
    except Exception as e:
        print(f"[ERROR] on_raw_bulk_message_delete: {e}")
```

### Step 2: Add Edit Handler

```python
# apps/bot/src/bot.py

@bot.event
async def on_raw_message_edit(payload: discord.RawMessageUpdateEvent) -> None:
    """
    Handle message edits - update Postgres and re-index in Qdrant.
    
    Uses raw event for reliability.
    
    Pipeline:
    1. Check if content actually changed
    2. Update content in Postgres
    3. Queue re-indexing if message was indexed
    """
    # Skip DMs and bot messages
    if not payload.guild_id:
        return
    
    # Get message data from payload
    data = payload.data
    message_id = payload.message_id
    guild_id = payload.guild_id
    
    # Check if this is a content edit (not just embed update)
    new_content = data.get("content")
    if new_content is None:
        # This might be an embed update, not a content edit
        return
    
    # Skip if it's a bot message
    author = data.get("author", {})
    if author.get("bot", False):
        return
    
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            # Get old content and check if it changed
            old_result = conn.execute(text("""
                SELECT content, qdrant_point_id
                FROM messages
                WHERE id = :message_id AND guild_id = :guild_id
            """), {"message_id": message_id, "guild_id": guild_id})
            
            old_row = old_result.fetchone()
            
            if not old_row:
                # Message not in our DB yet - shouldn't happen but handle gracefully
                return
            
            old_content = old_row.content
            qdrant_point_id = old_row.qdrant_point_id
            
            # Skip if content hasn't changed
            if old_content == new_content:
                return
            
            # Update content in Postgres
            conn.execute(text("""
                UPDATE messages
                SET content = :content, updated_at = NOW()
                WHERE id = :message_id AND guild_id = :guild_id
            """), {
                "content": new_content,
                "message_id": message_id,
                "guild_id": guild_id,
            })
            conn.commit()
            
            print(f"[EDIT] Updated message {message_id} in Postgres")
            
            # Queue re-indexing if message was indexed
            if qdrant_point_id:
                from apps.bot.src.tasks import reindex_message
                reindex_message.delay(
                    guild_id=guild_id,
                    message_id=message_id,
                    new_content=new_content,
                )
                print(f"[EDIT] Queued re-indexing for message {message_id}")
                
    except Exception as e:
        print(f"[ERROR] on_raw_message_edit: {e}")
```

### Step 3: Add Re-indexing Task

```python
# apps/bot/src/tasks.py

@celery_app.task(
    bind=True,
    name="reindex_message",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def reindex_message(
    self,
    guild_id: int,
    message_id: int,
    new_content: str,
) -> dict:
    """
    Re-index a message after edit.
    
    Strategy: Find the session containing this message and re-index the entire session.
    This ensures context is preserved.
    """
    engine = get_db_engine()
    
    with engine.connect() as conn:
        # Find the session containing this message
        result = conn.execute(text("""
            SELECT ms.id as session_id, ms.channel_id, c.name as channel_name
            FROM message_sessions ms
            JOIN channels c ON ms.channel_id = c.id
            WHERE ms.guild_id = :guild_id
              AND :message_id = ANY(
                  SELECT m.id FROM messages m 
                  WHERE m.id BETWEEN ms.start_message_id AND ms.end_message_id
              )
        """), {"guild_id": guild_id, "message_id": message_id})
        
        row = result.fetchone()
    
    if not row:
        # Message not part of any session - might be too recent
        return {"status": "skipped", "reason": "no_session_found"}
    
    # Get all messages in this session
    with engine.connect() as conn:
        messages_result = conn.execute(text("""
            SELECT id FROM messages
            WHERE guild_id = :guild_id
              AND id BETWEEN :start_id AND :end_id
              AND is_deleted = FALSE
            ORDER BY message_timestamp
        """), {
            "guild_id": guild_id,
            "start_id": row.start_message_id,
            "end_id": row.end_message_id,
        })
        
        message_ids = [r.id for r in messages_result.fetchall()]
    
    # Re-index the session
    from apps.bot.src.tasks import index_session
    index_session.delay(
        guild_id=guild_id,
        channel_id=row.channel_id,
        channel_name=row.channel_name,
        session_id=str(row.session_id),
        message_ids=message_ids,
        start_time=row.start_time.isoformat() if row.start_time else None,
        end_time=row.end_time.isoformat() if row.end_time else None,
    )
    
    return {
        "status": "reindex_queued",
        "session_id": str(row.session_id),
        "message_count": len(message_ids),
    }
```

---

## 5. Handling Edge Cases

### Uncached Messages

The `on_raw_*` events provide minimal data for uncached messages. Handle this gracefully:

```python
@bot.event
async def on_raw_message_edit(payload: discord.RawMessageUpdateEvent):
    # For uncached messages, we get raw data dict
    if payload.cached_message:
        # Full Message object available
        old_content = payload.cached_message.content
    else:
        # Only raw data available - need to query our DB
        old_content = None  # Will fetch from Postgres
```

### Partial Message Updates

Discord sends partial updates (e.g., just embed changes). Only process content changes:

```python
# Check if this is actually a content edit
if "content" not in payload.data:
    return  # Skip embed-only updates
```

### Rate Limiting Re-indexes

Avoid overwhelming the system with rapid edits:

```python
# apps/bot/src/tasks.py

@celery_app.task(
    bind=True,
    name="reindex_message",
    rate_limit="10/m",  # Max 10 re-indexes per minute
)
def reindex_message(self, ...):
    ...
```

---

## 6. Testing Strategy

### Unit Tests

```python
# tests/test_message_events.py

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_on_raw_message_delete_updates_postgres():
    """Test that delete handler soft-deletes in Postgres."""
    payload = MagicMock()
    payload.guild_id = 123
    payload.message_id = 456
    
    with patch("apps.bot.src.bot.get_db_engine") as mock_engine:
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = MagicMock(qdrant_point_id="abc")
        
        await on_raw_message_delete(payload)
        
        # Verify UPDATE was called
        mock_conn.execute.assert_called()
        call_args = mock_conn.execute.call_args
        assert "is_deleted = TRUE" in str(call_args)


@pytest.mark.asyncio
async def test_on_raw_message_edit_skips_same_content():
    """Test that edit handler skips if content unchanged."""
    payload = MagicMock()
    payload.guild_id = 123
    payload.message_id = 456
    payload.data = {"content": "same content", "author": {"bot": False}}
    
    with patch("apps.bot.src.bot.get_db_engine") as mock_engine:
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = MagicMock(
            content="same content",
            qdrant_point_id=None,
        )
        
        await on_raw_message_edit(payload)
        
        # Verify no UPDATE was called (only SELECT)
        assert mock_conn.execute.call_count == 1
```

### Integration Test

```python
@pytest.mark.asyncio
async def test_edit_triggers_reindex():
    """Test that editing an indexed message queues re-indexing."""
    # Create test message in DB with qdrant_point_id
    # Trigger on_raw_message_edit
    # Verify reindex_message.delay was called
    pass
```

---

## 7. Logging & Monitoring

Add structured logging for debugging:

```python
import logging

logger = logging.getLogger("discord.events")

@bot.event
async def on_raw_message_delete(payload):
    logger.info(
        "message_deleted",
        extra={
            "guild_id": payload.guild_id,
            "message_id": payload.message_id,
            "channel_id": payload.channel_id,
        }
    )
    ...
```

---

## 8. References

- [Discord.py Events](https://discordpy.readthedocs.io/en/stable/api.html#event-reference)
- [RawMessageUpdateEvent](https://discordpy.readthedocs.io/en/stable/api.html#discord.RawMessageUpdateEvent)
- [Message Cache Behavior](https://stackoverflow.com/questions/78343030/discord-py-on-message-edit-method)

---

## 9. Checklist

- [ ] Add `on_raw_message_delete` handler
- [ ] Add `on_raw_bulk_message_delete` handler
- [ ] Add `on_raw_message_edit` handler
- [ ] Add `reindex_message` Celery task
- [ ] Update `delete_message_vectors` task with real Qdrant deletion
- [ ] Add unit tests for event handlers
- [ ] Add integration tests for full pipeline
- [ ] Add logging for debugging
- [ ] Test with real Discord messages
