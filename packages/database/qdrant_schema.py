"""
Qdrant Collection Schema Definition
Enforces: Multi-tenant filtering via guild_id payload indexing

CRITICAL CONSTRAINT:
- All Qdrant payloads MUST include guild_id for strict multi-tenant filtering
- Cannot write to Qdrant without corresponding Postgres record (Hybrid Storage Integrity)
"""

from dataclasses import dataclass
from typing import Any
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PayloadSchemaType,
    TextIndexParams,
    TokenizerType,
    CreateCollection,
    OptimizersConfigDiff,
)


# Collection names
MESSAGES_COLLECTION = "discord_messages"
SESSIONS_COLLECTION = "discord_sessions"


@dataclass
class QdrantCollectionConfig:
    """Configuration for Qdrant collections."""
    
    name: str
    vector_size: int
    distance: Distance
    payload_schema: dict[str, PayloadSchemaType]
    text_index_fields: list[str]


COLLECTION_CONFIGS: dict[str, QdrantCollectionConfig] = {
    MESSAGES_COLLECTION: QdrantCollectionConfig(
        name=MESSAGES_COLLECTION,
        vector_size=1536,  # OpenAI text-embedding-3-small
        distance=Distance.COSINE,
        payload_schema={
            # REQUIRED: Multi-tenant filtering (indexed for performance)
            "guild_id": PayloadSchemaType.INTEGER,
            "channel_id": PayloadSchemaType.INTEGER,
            "author_id": PayloadSchemaType.INTEGER,
            
            # Postgres reference (for Hybrid Storage sync)
            "message_id": PayloadSchemaType.INTEGER,
            
            # Temporal filtering
            "timestamp": PayloadSchemaType.DATETIME,
            
            # Content (for hybrid search)
            "content": PayloadSchemaType.TEXT,
        },
        text_index_fields=["content"],
    ),
    SESSIONS_COLLECTION: QdrantCollectionConfig(
        name=SESSIONS_COLLECTION,
        vector_size=1536,
        distance=Distance.COSINE,
        payload_schema={
            # REQUIRED: Multi-tenant filtering
            "guild_id": PayloadSchemaType.INTEGER,
            "channel_id": PayloadSchemaType.INTEGER,
            
            # Postgres reference
            "session_id": PayloadSchemaType.KEYWORD,
            
            # Session metadata
            "start_time": PayloadSchemaType.DATETIME,
            "end_time": PayloadSchemaType.DATETIME,
            "message_count": PayloadSchemaType.INTEGER,
            
            # Topics for GraphRAG
            "topic_tags": PayloadSchemaType.KEYWORD,
            "summary": PayloadSchemaType.TEXT,
        },
        text_index_fields=["summary"],
    ),
}


async def ensure_collections(client: QdrantClient) -> None:
    """
    Create or verify Qdrant collections with proper indexing.
    
    INVARIANT: guild_id is always indexed for multi-tenant queries.
    """
    existing = {c.name for c in client.get_collections().collections}
    
    for config in COLLECTION_CONFIGS.values():
        if config.name in existing:
            continue
        
        # Create collection with vector params
        client.create_collection(
            collection_name=config.name,
            vectors_config=VectorParams(
                size=config.vector_size,
                distance=config.distance,
            ),
            optimizers_config=OptimizersConfigDiff(
                indexing_threshold=10000,
            ),
        )
        
        # Create payload indexes for filtering
        for field_name, field_type in config.payload_schema.items():
            client.create_payload_index(
                collection_name=config.name,
                field_name=field_name,
                field_schema=field_type,
            )
        
        # Create text indexes for hybrid search
        for field_name in config.text_index_fields:
            client.create_payload_index(
                collection_name=config.name,
                field_name=field_name,
                field_schema=TextIndexParams(
                    type="text",
                    tokenizer=TokenizerType.WORD,
                    min_token_len=2,
                    max_token_len=20,
                    lowercase=True,
                ),
            )


def validate_payload(payload: dict[str, Any], collection_name: str) -> None:
    """
    Validate payload before upserting to Qdrant.
    
    CRITICAL: Enforces guild_id requirement for multi-tenant isolation.
    
    Raises:
        ValueError: If guild_id is missing or payload is invalid.
    """
    if "guild_id" not in payload:
        raise ValueError(
            f"SECURITY: guild_id is REQUIRED in all Qdrant payloads. "
            f"Collection: {collection_name}"
        )
    
    if not isinstance(payload["guild_id"], int):
        raise ValueError(
            f"guild_id must be an integer (Discord snowflake). "
            f"Got: {type(payload['guild_id'])}"
        )
    
    config = COLLECTION_CONFIGS.get(collection_name)
    if not config:
        raise ValueError(f"Unknown collection: {collection_name}")


# Payload templates for type safety
@dataclass
class MessagePayload:
    """Payload structure for individual message vectors."""
    guild_id: int
    channel_id: int
    author_id: int
    message_id: int
    timestamp: str  # ISO format
    content: str
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "author_id": self.author_id,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "content": self.content,
        }


@dataclass
class SessionPayload:
    """Payload structure for session/chunk vectors."""
    guild_id: int
    channel_id: int
    session_id: str  # UUID
    start_time: str  # ISO format
    end_time: str    # ISO format
    message_count: int
    topic_tags: list[str]
    summary: str
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "session_id": self.session_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "message_count": self.message_count,
            "topic_tags": self.topic_tags,
            "summary": self.summary,
        }
