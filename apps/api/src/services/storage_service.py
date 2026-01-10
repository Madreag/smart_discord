"""
Hybrid Storage Service - Manages Postgres + Qdrant consistency.

INVARIANT: Postgres is always written first, Qdrant async.

This service ensures data consistency between PostgreSQL (source of truth)
and Qdrant (semantic search index).
"""

from typing import Optional
from uuid import uuid4
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import create_engine, text

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


@dataclass
class SyncHealth:
    """Health metrics for Postgres-Qdrant sync."""
    guild_id: int
    total_messages: int
    synced: int
    pending: int
    stale: int
    sync_percentage: float
    health: str  # "healthy", "degraded", "critical"


class HybridStorageService:
    """
    Manages dual-write to Postgres and Qdrant.
    
    Usage:
        service = HybridStorageService()
        
        # Mark session as indexed
        await service.mark_session_indexed(session_id, qdrant_point_id)
        
        # Get sync health
        health = await service.get_sync_health(guild_id)
    """
    
    def __init__(self):
        settings = get_settings()
        self._engine = None
        self._db_url = settings.database_url.replace("+asyncpg", "")
    
    @property
    def engine(self):
        """Lazy-load database engine."""
        if self._engine is None:
            self._engine = create_engine(self._db_url, pool_pre_ping=True)
        return self._engine
    
    def mark_session_indexed(
        self,
        session_id: str,
        qdrant_point_id: str,
        message_ids: list[int] = None,
    ) -> bool:
        """
        Mark a session as indexed in Qdrant.
        
        Updates:
        - message_sessions.qdrant_point_id
        - messages.indexed_at for all messages in session
        """
        try:
            with self.engine.connect() as conn:
                # Update session with Qdrant point ID
                conn.execute(text("""
                    UPDATE message_sessions
                    SET qdrant_point_id = :point_id
                    WHERE id = :session_id
                """), {
                    "point_id": qdrant_point_id,
                    "session_id": session_id,
                })
                
                # Mark messages as indexed
                if message_ids:
                    conn.execute(text("""
                        UPDATE messages
                        SET indexed_at = NOW(), qdrant_point_id = :point_id
                        WHERE id = ANY(:ids)
                    """), {
                        "point_id": qdrant_point_id,
                        "ids": message_ids,
                    })
                
                conn.commit()
            
            print(f"[SYNC] Marked session {session_id} as indexed (point: {qdrant_point_id[:8]}...)")
            return True
            
        except Exception as e:
            print(f"[SYNC] Failed to mark session indexed: {e}")
            return False
    
    def get_sync_status(self, message_id: int) -> Optional[SyncStatus]:
        """Get sync status of a message."""
        try:
            with self.engine.connect() as conn:
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
            if row.indexed_at and row.updated_at and row.updated_at > row.indexed_at:
                return SyncStatus.STALE
            return SyncStatus.SYNCED
            
        except Exception:
            return None
    
    def get_unsynced_count(self, guild_id: int) -> int:
        """Get count of messages not yet synced to Qdrant."""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT COUNT(*) FROM messages m
                    JOIN channels c ON m.channel_id = c.id
                    WHERE m.guild_id = :guild_id
                      AND m.is_deleted = FALSE
                      AND m.qdrant_point_id IS NULL
                      AND c.is_indexed = TRUE
                """), {"guild_id": guild_id})
                return result.scalar() or 0
        except Exception:
            return 0
    
    def get_unsynced_messages(
        self,
        guild_id: int,
        limit: int = 100,
    ) -> list[int]:
        """Get message IDs that need syncing."""
        try:
            with self.engine.connect() as conn:
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
        except Exception:
            return []
    
    def get_stale_messages(
        self,
        guild_id: int,
        limit: int = 100,
    ) -> list[int]:
        """Get message IDs that need re-syncing (edited after indexing)."""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT id
                    FROM messages
                    WHERE guild_id = :guild_id
                      AND is_deleted = FALSE
                      AND qdrant_point_id IS NOT NULL
                      AND indexed_at IS NOT NULL
                      AND updated_at > indexed_at
                    LIMIT :limit
                """), {"guild_id": guild_id, "limit": limit})
                
                return [row.id for row in result.fetchall()]
        except Exception:
            return []
    
    def get_sync_health(self, guild_id: int) -> SyncHealth:
        """Get sync health metrics for a guild."""
        try:
            with self.engine.connect() as conn:
                # Total messages in indexed channels
                total = conn.execute(text("""
                    SELECT COUNT(*) FROM messages m
                    JOIN channels c ON m.channel_id = c.id
                    WHERE m.guild_id = :g 
                      AND m.is_deleted = FALSE
                      AND c.is_indexed = TRUE
                """), {"g": guild_id}).scalar() or 0
                
                # Synced (has qdrant_point_id)
                synced = conn.execute(text("""
                    SELECT COUNT(*) FROM messages m
                    JOIN channels c ON m.channel_id = c.id
                    WHERE m.guild_id = :g 
                      AND m.qdrant_point_id IS NOT NULL
                      AND c.is_indexed = TRUE
                """), {"g": guild_id}).scalar() or 0
                
                # Pending (no qdrant_point_id)
                pending = conn.execute(text("""
                    SELECT COUNT(*) FROM messages m
                    JOIN channels c ON m.channel_id = c.id
                    WHERE m.guild_id = :g 
                      AND m.is_deleted = FALSE 
                      AND m.qdrant_point_id IS NULL
                      AND c.is_indexed = TRUE
                """), {"g": guild_id}).scalar() or 0
                
                # Stale (updated after indexing)
                stale = conn.execute(text("""
                    SELECT COUNT(*) FROM messages
                    WHERE guild_id = :g 
                      AND indexed_at IS NOT NULL
                      AND updated_at > indexed_at
                """), {"g": guild_id}).scalar() or 0
            
            sync_percentage = (synced / total * 100) if total > 0 else 100.0
            
            if sync_percentage >= 95:
                health = "healthy"
            elif sync_percentage >= 80:
                health = "degraded"
            else:
                health = "critical"
            
            return SyncHealth(
                guild_id=guild_id,
                total_messages=total,
                synced=synced,
                pending=pending,
                stale=stale,
                sync_percentage=round(sync_percentage, 2),
                health=health,
            )
            
        except Exception as e:
            print(f"[SYNC] Error getting sync health: {e}")
            return SyncHealth(
                guild_id=guild_id,
                total_messages=0,
                synced=0,
                pending=0,
                stale=0,
                sync_percentage=0.0,
                health="unknown",
            )
    
    def verify_qdrant_points(
        self,
        guild_id: int,
        qdrant_point_ids: list[str],
    ) -> dict:
        """
        Verify which Qdrant points exist in Postgres.
        
        Returns:
            {
                "valid": [...],      # Points that have matching Postgres records
                "orphaned": [...],   # Points in Qdrant but not in Postgres
            }
        """
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT DISTINCT qdrant_point_id::text
                    FROM messages
                    WHERE guild_id = :guild_id
                      AND qdrant_point_id = ANY(:point_ids::uuid[])
                """), {
                    "guild_id": guild_id,
                    "point_ids": qdrant_point_ids,
                })
                valid = {row[0] for row in result.fetchall()}
            
            orphaned = [p for p in qdrant_point_ids if p not in valid]
            
            return {
                "valid": list(valid),
                "orphaned": orphaned,
            }
        except Exception as e:
            print(f"[SYNC] Error verifying Qdrant points: {e}")
            return {"valid": [], "orphaned": []}
    
    def reset_sync_status(
        self,
        guild_id: int,
        force: bool = False,
    ) -> int:
        """
        Reset sync status to trigger re-indexing.
        
        Args:
            guild_id: Target guild
            force: If True, reset all messages. If False, only pending/stale.
            
        Returns:
            Number of messages reset
        """
        try:
            with self.engine.connect() as conn:
                if force:
                    result = conn.execute(text("""
                        UPDATE messages
                        SET qdrant_point_id = NULL, indexed_at = NULL
                        WHERE guild_id = :guild_id AND is_deleted = FALSE
                    """), {"guild_id": guild_id})
                else:
                    result = conn.execute(text("""
                        UPDATE messages
                        SET qdrant_point_id = NULL, indexed_at = NULL
                        WHERE guild_id = :guild_id 
                          AND is_deleted = FALSE
                          AND (qdrant_point_id IS NULL OR updated_at > indexed_at)
                    """), {"guild_id": guild_id})
                
                count = result.rowcount
                conn.commit()
            
            print(f"[SYNC] Reset sync status for {count} messages in guild {guild_id}")
            return count
            
        except Exception as e:
            print(f"[SYNC] Error resetting sync status: {e}")
            return 0
    
    def reset_channel_sync_status(self, guild_id: int, channel_id: int) -> int:
        """
        Reset sync status for a specific channel to trigger re-indexing.
        
        Args:
            guild_id: Target guild
            channel_id: Target channel
            
        Returns:
            Number of messages reset
        """
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    UPDATE messages
                    SET qdrant_point_id = NULL, indexed_at = NULL
                    WHERE guild_id = :guild_id 
                      AND channel_id = :channel_id 
                      AND is_deleted = FALSE
                """), {"guild_id": guild_id, "channel_id": channel_id})
                
                count = result.rowcount
                conn.commit()
            
            print(f"[SYNC] Reset sync status for {count} messages in channel {channel_id}")
            return count
            
        except Exception as e:
            print(f"[SYNC] Error resetting channel sync status: {e}")
            return 0


# Global service instance
storage_service = HybridStorageService()
