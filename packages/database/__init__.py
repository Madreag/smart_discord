"""
Database package for Discord Community Intelligence System.

Hybrid Storage Model:
- PostgreSQL: Source of Truth (User/Guild config, messages)
- Qdrant: Semantic Index (Vector embeddings with guild_id filtering)
"""

from .qdrant_schema import (
    MESSAGES_COLLECTION,
    SESSIONS_COLLECTION,
    ensure_collections,
    validate_payload,
    MessagePayload,
    SessionPayload,
)

__all__ = [
    "MESSAGES_COLLECTION",
    "SESSIONS_COLLECTION",
    "ensure_collections",
    "validate_payload",
    "MessagePayload",
    "SessionPayload",
]
