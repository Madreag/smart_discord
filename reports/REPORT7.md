# REPORT 7: Hybrid Storage Design (PostgreSQL + Qdrant)

> **Priority**: Partial Implementation  
> **Effort**: 2-3 days to complete  
> **Status**: Schema exists, sync logic incomplete

---

## 1. Executive Summary

The "Hybrid Storage" approach uses PostgreSQL as the **source of truth** for relational data (messages, users, analytics) and Qdrant as the **semantic index** for vector search. This is partially implemented:

**✅ Implemented**:
- PostgreSQL schema with `qdrant_point_id` column
- `is_indexed` flag on channels
- `is_deleted` soft delete flag

**❌ Missing**:
- Dual-write consistency
- Sync verification
- Batch synchronization jobs
- Error recovery

---

## 2. Current Schema Analysis

### What Exists

```sql
-- messages table
qdrant_point_id UUID,        -- Link to Qdrant point
indexed_at TIMESTAMP,        -- When indexed
is_deleted BOOLEAN,          -- Soft delete flag

-- channels table
is_indexed BOOLEAN,          -- Admin control flag

-- message_sessions table
qdrant_point_id UUID,        -- Link to Qdrant session point
```

### The Gap

The schema supports hybrid storage, but:
1. `qdrant_point_id` is never populated
2. No verification that Postgres and Qdrant are in sync
3. No recovery mechanism for failed writes

---

## 3. Hybrid Storage Principles

### The Dual-Write Problem

Writing to two databases creates consistency challenges:

```
Scenario 1: Postgres succeeds, Qdrant fails
→ Message exists in DB but not searchable

Scenario 2: Qdrant succeeds, Postgres fails
→ Search returns results that don't exist in DB

Scenario 3: Both succeed but with different data
→ Stale vectors, wrong content
```

### Solution: Postgres-First with Async Sync

```
1. Write to Postgres FIRST (synchronous)
2. Queue Qdrant write (async via Celery)
3. Update qdrant_point_id on success
4. Periodic verification job
```

---

## 4. Implementation Guide

### Step 1: Dual-Write Service

```python
# apps/api/src/services/storage_service.py
"""
Hybrid Storage Service - Manages Postgres + Qdrant consistency.

INVARIANT: Postgres is always written first, Qdrant async.
"""

from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from apps.api.src.core.config import get_settings


class SyncStatus(str, Enum):
    """Status of Postgres-Qdrant sync."""
    PENDING = "pending"      # In Postgres, not yet in Qdrant
    SYNCED = "synced"        # In both
    FAILED = "failed"        # Qdrant write failed
    STALE = "stale"          # Needs re-sync (edited)
    DELETED = "deleted"      # Soft deleted in Postgres


@dataclass
class StorageResult:
    """Result of a storage operation."""
    success: bool
    message_id: Optional[int] = None
    session_id: Optional[str] = None
    qdrant_point_id: Optional[str] = None
    sync_status: SyncStatus = SyncStatus.PENDING
    error: Optional[str] = None


class HybridStorageService:
    """
    Manages dual-write to Postgres and Qdrant.
    
    Usage:
        service = HybridStorageService()
        
        # Store message (Postgres first, Qdrant queued)
        result = await service.store_message(message_data)
        
        # Verify sync status
        status = await service.get_sync_status(message_id)
    """
    
    def __init__(self):
        settings = get_settings()
        self.sync_engine = create_engine(
            settings.database_url.replace("+asyncpg", ""),
            pool_pre_ping=True,
        )
    
    async def store_message(
        self,
        message_id: int,
        guild_id: int,
        channel_id: int,
        author_id: int,
        content: str,
        timestamp: datetime,
        reply_to_id: Optional[int] = None,
    ) -> StorageResult:
        """
        Store a message with Postgres-first strategy.
        
        1. Insert into Postgres (sync)
        2. Queue indexing task (async)
        """
        try:
            with self.sync_engine.connect() as conn:
                # Insert message
                conn.execute(text("""
                    INSERT INTO messages (
                        id, guild_id, channel_id, author_id, content,
                        message_timestamp, reply_to_id, created_at, updated_at
                    ) VALUES (
                        :id, :guild_id, :channel_id, :author_id, :content,
                        :timestamp, :reply_to_id, NOW(), NOW()
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        content = EXCLUDED.content,
                        updated_at = NOW()
                """), {
                    "id": message_id,
                    "guild_id": guild_id,
                    "channel_id": channel_id,
                    "author_id": author_id,
                    "content": content,
                    "timestamp": timestamp,
                    "reply_to_id": reply_to_id,
                })
                conn.commit()
            
            # Queue for indexing (async)
            # Note: Actual indexing happens in Celery task
            from apps.bot.src.tasks import queue_message_for_indexing
            queue_message_for_indexing.delay(
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=message_id,
            )
            
            return StorageResult(
                success=True,
                message_id=message_id,
                sync_status=SyncStatus.PENDING,
            )
            
        except Exception as e:
            return StorageResult(
                success=False,
                message_id=message_id,
                error=str(e),
            )
    
    async def mark_indexed(
        self,
        message_id: int,
        qdrant_point_id: str,
    ) -> bool:
        """Mark a message as indexed in Qdrant."""
        try:
            with self.sync_engine.connect() as conn:
                conn.execute(text("""
                    UPDATE messages
                    SET qdrant_point_id = :point_id, indexed_at = NOW()
                    WHERE id = :message_id
                """), {
                    "point_id": qdrant_point_id,
                    "message_id": message_id,
                })
                conn.commit()
            return True
        except Exception:
            return False
    
    async def mark_session_indexed(
        self,
        session_id: str,
        qdrant_point_id: str,
    ) -> bool:
        """Mark a session as indexed."""
        try:
            with self.sync_engine.connect() as conn:
                conn.execute(text("""
                    UPDATE message_sessions
                    SET qdrant_point_id = :point_id
                    WHERE id = :session_id
                """), {
                    "point_id": qdrant_point_id,
                    "session_id": session_id,
                })
                conn.commit()
            return True
        except Exception:
            return False
    
    async def get_sync_status(self, message_id: int) -> SyncStatus:
        """Get sync status of a message."""
        with self.sync_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT is_deleted, qdrant_point_id, indexed_at, updated_at
                FROM messages
                WHERE id = :id
            """), {"id": message_id})
            row = result.fetchone()
        
        if not row:
            return None
        
        if row.is_deleted:
            return SyncStatus.DELETED
        if row.qdrant_point_id is None:
            return SyncStatus.PENDING
        if row.indexed_at and row.updated_at > row.indexed_at:
            return SyncStatus.STALE
        return SyncStatus.SYNCED
    
    async def get_unsynced_messages(
        self,
        guild_id: int,
        limit: int = 100,
    ) -> list[int]:
        """Get message IDs that need syncing."""
        with self.sync_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT m.id
                FROM messages m
                JOIN channels c ON m.channel_id = c.id
                WHERE m.guild_id = :guild_id
                  AND m.is_deleted = FALSE
                  AND m.qdrant_point_id IS NULL
                  AND c.is_indexed = TRUE
                ORDER BY m.message_timestamp DESC
                LIMIT :limit
            """), {"guild_id": guild_id, "limit": limit})
            
            return [row.id for row in result.fetchall()]
    
    async def get_stale_messages(
        self,
        guild_id: int,
        limit: int = 100,
    ) -> list[int]:
        """Get message IDs that need re-syncing (edited after indexing)."""
        with self.sync_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT id
                FROM messages
                WHERE guild_id = :guild_id
                  AND is_deleted = FALSE
                  AND qdrant_point_id IS NOT NULL
                  AND updated_at > indexed_at
                LIMIT :limit
            """), {"guild_id": guild_id, "limit": limit})
            
            return [row.id for row in result.fetchall()]


# Global service instance
storage_service = HybridStorageService()
```

### Step 2: Sync Verification Job

```python
# apps/bot/src/tasks.py (add sync verification)

@celery_app.task(bind=True, name="verify_sync")
def verify_sync(self, guild_id: int) -> dict:
    """
    Verify Postgres-Qdrant sync for a guild.
    
    Checks:
    1. Messages in Postgres but not Qdrant
    2. Sessions in Postgres but not Qdrant
    3. Stale entries needing re-index
    """
    import asyncio
    from apps.api.src.services.storage_service import storage_service
    from apps.api.src.services.qdrant_service import qdrant_service
    
    # Get unsynced messages
    unsynced = asyncio.run(storage_service.get_unsynced_messages(guild_id))
    stale = asyncio.run(storage_service.get_stale_messages(guild_id))
    
    # Queue re-indexing for unsynced
    for msg_id in unsynced[:100]:  # Limit batch size
        queue_message_for_indexing.delay(guild_id, msg_id)
    
    return {
        "guild_id": guild_id,
        "unsynced_count": len(unsynced),
        "stale_count": len(stale),
        "queued_for_sync": min(len(unsynced), 100),
    }


@celery_app.task(bind=True, name="repair_sync")
def repair_sync(self, guild_id: int, force: bool = False) -> dict:
    """
    Repair sync issues between Postgres and Qdrant.
    
    If force=True, re-indexes everything regardless of status.
    """
    engine = get_db_engine()
    
    with engine.connect() as conn:
        if force:
            # Mark all messages as needing re-index
            result = conn.execute(text("""
                UPDATE messages
                SET qdrant_point_id = NULL, indexed_at = NULL
                WHERE guild_id = :guild_id AND is_deleted = FALSE
                RETURNING id
            """), {"guild_id": guild_id})
            count = len(result.fetchall())
            conn.commit()
        else:
            # Only get currently unsynced
            result = conn.execute(text("""
                SELECT COUNT(*) FROM messages
                WHERE guild_id = :guild_id
                  AND is_deleted = FALSE
                  AND qdrant_point_id IS NULL
            """), {"guild_id": guild_id})
            count = result.scalar()
    
    # Trigger batch indexing
    batch_index_guild.delay(guild_id)
    
    return {
        "guild_id": guild_id,
        "messages_to_sync": count,
        "force_reindex": force,
    }
```

### Step 3: Periodic Sync Celery Beat

```python
# apps/bot/src/celery_config.py

from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    # Verify sync every hour
    "verify-sync-hourly": {
        "task": "verify_sync_all_guilds",
        "schedule": crontab(minute=0),  # Every hour
    },
    # Full repair weekly
    "repair-sync-weekly": {
        "task": "repair_sync_all_guilds",
        "schedule": crontab(hour=3, minute=0, day_of_week=0),  # Sunday 3am
    },
}


@celery_app.task(name="verify_sync_all_guilds")
def verify_sync_all_guilds():
    """Run sync verification for all active guilds."""
    engine = get_db_engine()
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id FROM guilds WHERE is_active = TRUE
        """))
        guild_ids = [row.id for row in result.fetchall()]
    
    for guild_id in guild_ids:
        verify_sync.delay(guild_id)
    
    return {"guilds_queued": len(guild_ids)}
```

---

## 5. Monitoring & Alerting

### Sync Health Dashboard Endpoint

```python
# apps/api/src/main.py

@app.get("/guilds/{guild_id}/sync-health")
async def get_sync_health(guild_id: int) -> dict:
    """Get sync health metrics for a guild."""
    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    
    with engine.connect() as conn:
        # Total messages
        total = conn.execute(text("""
            SELECT COUNT(*) FROM messages
            WHERE guild_id = :g AND is_deleted = FALSE
        """), {"g": guild_id}).scalar()
        
        # Synced
        synced = conn.execute(text("""
            SELECT COUNT(*) FROM messages
            WHERE guild_id = :g AND qdrant_point_id IS NOT NULL
        """), {"g": guild_id}).scalar()
        
        # Pending
        pending = conn.execute(text("""
            SELECT COUNT(*) FROM messages
            WHERE guild_id = :g AND is_deleted = FALSE AND qdrant_point_id IS NULL
        """), {"g": guild_id}).scalar()
        
        # Stale
        stale = conn.execute(text("""
            SELECT COUNT(*) FROM messages
            WHERE guild_id = :g AND updated_at > indexed_at
        """), {"g": guild_id}).scalar()
    
    sync_percentage = (synced / total * 100) if total > 0 else 100
    
    return {
        "guild_id": guild_id,
        "total_messages": total,
        "synced": synced,
        "pending": pending,
        "stale": stale,
        "sync_percentage": round(sync_percentage, 2),
        "health": "healthy" if sync_percentage > 95 else "degraded",
    }
```

---

## 6. Error Recovery

### Failed Qdrant Writes

```python
@celery_app.task(
    bind=True,
    name="index_with_retry",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=3600,  # Max 1 hour
    max_retries=5,
)
def index_with_retry(self, guild_id: int, session_id: str, ...):
    """Index with automatic retry on failure."""
    try:
        # ... indexing logic ...
        pass
    except Exception as e:
        # Log failure
        print(f"Index failed for session {session_id}: {e}")
        
        # Mark as failed in Postgres
        with get_db_engine().connect() as conn:
            conn.execute(text("""
                UPDATE message_sessions
                SET sync_status = 'failed', sync_error = :error
                WHERE id = :session_id
            """), {"session_id": session_id, "error": str(e)})
            conn.commit()
        
        raise  # Re-raise for retry
```

---

## 7. References

- [Dual Write Problem](https://www.confluent.io/blog/dual-write-problem/)
- [Saga Pattern](https://microservices.io/patterns/data/saga.html)
- [Outbox Pattern](https://microservices.io/patterns/data/transactional-outbox.html)

---

## 8. Checklist

- [ ] Create `apps/api/src/services/storage_service.py`
- [ ] Add `sync_status` column to `message_sessions` table
- [ ] Implement `mark_indexed` / `mark_session_indexed`
- [ ] Add `verify_sync` Celery task
- [ ] Add `repair_sync` Celery task
- [ ] Set up Celery Beat schedule
- [ ] Add `/sync-health` API endpoint
- [ ] Add sync health to dashboard UI
- [ ] Test failure recovery scenarios
