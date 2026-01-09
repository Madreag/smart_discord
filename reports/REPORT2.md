# REPORT 2: Qdrant Vector Indexing Pipeline

> **Priority**: P0 (Critical)  
> **Effort**: 1-2 days  
> **Status**: Scaffolded (TODO placeholders)

---

## 1. Executive Summary

The Celery tasks for vector indexing exist but contain `# TODO` comments with no actual implementation. Messages are saved to PostgreSQL but never embedded or indexed to Qdrant, making the RAG system non-functional.

**Target State**: Complete pipeline that embeds message sessions and upserts to Qdrant with multi-tenant filtering.

---

## 2. Current Implementation Analysis

### What Exists

```python
# apps/bot/src/tasks.py (current - scaffolded)
@celery_app.task(bind=True, name="index_messages")
def index_messages(self, payload_dict: dict) -> dict:
    payload = IndexTaskPayload(**payload_dict)
    
    # TODO: Implement actual indexing logic
    # 1. Verify messages exist in Postgres
    # 2. Generate embeddings
    # 3. Upsert to Qdrant with guild_id in payload
    # 4. Update qdrant_point_id in Postgres
    
    return {"status": "success", ...}  # Does nothing!
```

### The Gap

- No embedding model initialization
- No Qdrant client setup
- No actual vector operations
- No Postgres ↔ Qdrant sync

---

## 3. Architecture Design

### Data Flow

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌─────────────┐
│   Discord   │────▶│  PostgreSQL  │────▶│  Sessionizer │────▶│  Embedding  │
│   Message   │     │   (Source)   │     │  (Grouping)  │     │   Model     │
└─────────────┘     └──────────────┘     └─────────────┘     └─────────────┘
                                                                     │
                                                                     ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌─────────────┐
│   Update    │◀────│   Qdrant     │◀────│   Upsert    │◀────│   Vector    │
│  Postgres   │     │  (Vectors)   │     │   Batch     │     │   384-dim   │
└─────────────┘     └──────────────┘     └─────────────┘     └─────────────┘
```

### Multi-Tenant Isolation

Every Qdrant point MUST include `guild_id` in the payload for filtering:

```python
payload = {
    "guild_id": 123456789,      # REQUIRED - multi-tenant filter
    "channel_id": 987654321,    # Optional filter
    "message_ids": [1, 2, 3],   # Messages in this session
    "start_time": "2025-01-01T00:00:00Z",
    "end_time": "2025-01-01T00:15:00Z",
    "content": "Preview text...",
}
```

---

## 4. Implementation Guide

### Step 1: Dependencies

```bash
# Add to apps/api/pyproject.toml
pip install qdrant-client>=1.7.0 fastembed>=0.2.0
```

**Why FastEmbed?**
- CPU-optimized (no GPU required)
- Bundled with Qdrant client
- 384-dimension `all-MiniLM-L6-v2` model
- ~50ms per embedding on modern CPU

### Step 2: Embedding Service

```python
# apps/api/src/services/embedding_service.py
"""
Embedding Service - Generates vector embeddings for message sessions.

Uses FastEmbed for efficient local embedding (no API costs).
Model: all-MiniLM-L6-v2 (384 dimensions, good quality/speed balance)
"""

from typing import Optional
from functools import lru_cache


# Lazy-load model to avoid startup delay
_embedding_model = None


def get_embedding_model():
    """Get or create the embedding model (singleton pattern)."""
    global _embedding_model
    if _embedding_model is None:
        from fastembed import TextEmbedding
        
        # Options:
        # - "all-MiniLM-L6-v2": 384 dims, fast, good quality
        # - "BAAI/bge-small-en-v1.5": 384 dims, better quality
        # - "BAAI/bge-base-en-v1.5": 768 dims, best quality, slower
        _embedding_model = TextEmbedding(model_name="all-MiniLM-L6-v2")
    return _embedding_model


def generate_embedding(text: str) -> list[float]:
    """
    Generate embedding for a single text.
    
    Args:
        text: Text to embed (recommended: <512 tokens)
        
    Returns:
        384-dimensional float vector
    """
    model = get_embedding_model()
    # FastEmbed returns a generator, convert to list
    embeddings = list(model.embed([text]))
    return embeddings[0].tolist()


def generate_embeddings_batch(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """
    Generate embeddings for multiple texts efficiently.
    
    Args:
        texts: List of texts to embed
        batch_size: Batch size for processing
        
    Returns:
        List of 384-dimensional vectors
    """
    if not texts:
        return []
    
    model = get_embedding_model()
    embeddings = list(model.embed(texts, batch_size=batch_size))
    return [e.tolist() for e in embeddings]


# Alternative: OpenAI embeddings for higher quality
async def generate_embedding_openai(text: str) -> list[float]:
    """
    Generate embedding using OpenAI API.
    
    Pros: Higher quality, 1536 dimensions
    Cons: API cost (~$0.0001 per 1K tokens), latency
    """
    from openai import AsyncOpenAI
    from apps.api.src.core.config import get_settings
    
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    response = await client.embeddings.create(
        model="text-embedding-3-small",  # or text-embedding-3-large
        input=text,
    )
    
    return response.data[0].embedding
```

### Step 3: Qdrant Service

```python
# apps/api/src/services/qdrant_service.py
"""
Qdrant Service - Vector database operations with multi-tenant isolation.

INVARIANT: All operations MUST include guild_id in filter/payload.
"""

from typing import Optional
from uuid import UUID
import asyncio

from qdrant_client import QdrantClient, AsyncQdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    MatchAny,
    PayloadSchemaType,
)

from apps.api.src.core.config import get_settings


# Collection configuration
COLLECTION_NAME = "discord_messages"
VECTOR_SIZE = 384  # Must match embedding model


class QdrantService:
    """Async Qdrant client wrapper with multi-tenant support."""
    
    def __init__(self):
        self._client: Optional[AsyncQdrantClient] = None
    
    async def get_client(self) -> AsyncQdrantClient:
        """Get or create async Qdrant client."""
        if self._client is None:
            settings = get_settings()
            self._client = AsyncQdrantClient(
                url=settings.qdrant_url,
                timeout=30.0,
            )
        return self._client
    
    async def ensure_collection(self) -> None:
        """Create collection and indexes if they don't exist."""
        client = await self.get_client()
        
        collections = await client.get_collections()
        existing = [c.name for c in collections.collections]
        
        if COLLECTION_NAME not in existing:
            await client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=VECTOR_SIZE,
                    distance=Distance.COSINE,
                ),
                # Optimized for filtering by guild_id
                optimizers_config=models.OptimizersConfigDiff(
                    indexing_threshold=10000,
                ),
            )
            
            # Create payload indexes for efficient filtering
            await client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name="guild_id",
                field_schema=PayloadSchemaType.INTEGER,
            )
            await client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name="channel_id",
                field_schema=PayloadSchemaType.INTEGER,
            )
            
            print(f"Created Qdrant collection: {COLLECTION_NAME}")
    
    async def upsert_session(
        self,
        session_id: str,
        guild_id: int,
        channel_id: int,
        embedding: list[float],
        message_ids: list[int],
        content_preview: str,
        start_time: str,
        end_time: str,
        author_ids: Optional[list[int]] = None,
    ) -> bool:
        """
        Upsert a message session vector.
        
        Args:
            session_id: UUID for the session (Qdrant point ID)
            guild_id: Discord guild ID (REQUIRED)
            channel_id: Discord channel ID
            embedding: Vector embedding (384 dims)
            message_ids: List of message IDs in session
            content_preview: Truncated content for display
            start_time: ISO timestamp
            end_time: ISO timestamp
            author_ids: List of author IDs in session
            
        Returns:
            True if successful
        """
        client = await self.get_client()
        
        payload = {
            "guild_id": guild_id,
            "channel_id": channel_id,
            "message_ids": message_ids,
            "message_count": len(message_ids),
            "content": content_preview[:1000],  # Limit payload size
            "start_time": start_time,
            "end_time": end_time,
            "author_ids": author_ids or [],
        }
        
        result = await client.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                PointStruct(
                    id=session_id,
                    vector=embedding,
                    payload=payload,
                )
            ],
            wait=True,
        )
        
        return result.status == models.UpdateStatus.COMPLETED
    
    async def upsert_batch(
        self,
        points: list[dict],
    ) -> bool:
        """
        Batch upsert multiple sessions.
        
        Args:
            points: List of dicts with keys:
                - id: str (UUID)
                - vector: list[float]
                - payload: dict
                
        Returns:
            True if successful
        """
        client = await self.get_client()
        
        qdrant_points = [
            PointStruct(
                id=p["id"],
                vector=p["vector"],
                payload=p["payload"],
            )
            for p in points
        ]
        
        result = await client.upsert(
            collection_name=COLLECTION_NAME,
            points=qdrant_points,
            wait=True,
        )
        
        return result.status == models.UpdateStatus.COMPLETED
    
    async def search(
        self,
        query_embedding: list[float],
        guild_id: int,
        channel_ids: Optional[list[int]] = None,
        limit: int = 5,
        score_threshold: float = 0.5,
    ) -> list[dict]:
        """
        Search for similar vectors with multi-tenant filtering.
        
        Args:
            query_embedding: Query vector
            guild_id: Guild ID (REQUIRED for isolation)
            channel_ids: Optional channel filter
            limit: Max results
            score_threshold: Minimum similarity score
            
        Returns:
            List of results with id, score, payload
        """
        client = await self.get_client()
        
        # Build filter - guild_id is ALWAYS required
        must_conditions = [
            FieldCondition(
                key="guild_id",
                match=MatchValue(value=guild_id),
            ),
        ]
        
        if channel_ids:
            must_conditions.append(
                FieldCondition(
                    key="channel_id",
                    match=MatchAny(any=channel_ids),
                )
            )
        
        results = await client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_embedding,
            query_filter=Filter(must=must_conditions),
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
        )
        
        return [
            {
                "id": str(r.id),
                "score": r.score,
                "payload": r.payload,
            }
            for r in results
        ]
    
    async def delete_by_session_id(self, session_id: str) -> bool:
        """Delete a session by ID."""
        client = await self.get_client()
        
        result = await client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=models.PointIdsList(
                points=[session_id],
            ),
        )
        
        return result.status == models.UpdateStatus.COMPLETED
    
    async def delete_by_message_ids(
        self,
        guild_id: int,
        message_ids: list[int],
    ) -> int:
        """
        Delete sessions containing specific message IDs.
        
        Used for "Right to be Forgotten" compliance.
        
        Returns:
            Number of points deleted
        """
        client = await self.get_client()
        
        # Find sessions containing these messages
        # Note: This requires iterating - could be optimized with a dedicated index
        deleted_count = 0
        
        for msg_id in message_ids:
            result = await client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=models.FilterSelector(
                    filter=Filter(
                        must=[
                            FieldCondition(
                                key="guild_id",
                                match=MatchValue(value=guild_id),
                            ),
                            FieldCondition(
                                key="message_ids",
                                match=MatchAny(any=[msg_id]),
                            ),
                        ]
                    )
                ),
            )
            if result.status == models.UpdateStatus.COMPLETED:
                deleted_count += 1
        
        return deleted_count


# Global service instance
qdrant_service = QdrantService()
```

### Step 4: Enrichment Service

```python
# apps/api/src/services/enrichment_service.py
"""
Metadata Enrichment - Prepends context to text before embedding.

Format: "[Author @ timestamp]: content"

This helps embeddings capture WHO said WHAT and WHEN.
"""

from datetime import datetime
from typing import Optional


def enrich_message(
    content: str,
    author_name: str,
    timestamp: datetime,
    channel_name: Optional[str] = None,
) -> str:
    """
    Enrich a single message with metadata.
    
    Args:
        content: Original message content
        author_name: Display name of author
        timestamp: When message was sent
        channel_name: Optional channel context
        
    Returns:
        Enriched text for embedding
    """
    time_str = timestamp.strftime("%Y-%m-%d %H:%M")
    
    if channel_name:
        return f"[{author_name} in #{channel_name} @ {time_str}]: {content}"
    
    return f"[{author_name} @ {time_str}]: {content}"


def enrich_session(
    messages: list[dict],
    channel_name: Optional[str] = None,
) -> str:
    """
    Enrich a session of messages.
    
    Args:
        messages: List of dicts with 'content', 'author_name', 'timestamp'
        channel_name: Channel context
        
    Returns:
        Concatenated enriched text
    """
    lines = []
    
    for msg in messages:
        enriched = enrich_message(
            content=msg["content"],
            author_name=msg["author_name"],
            timestamp=msg["timestamp"],
            channel_name=None,  # Don't repeat channel on each line
        )
        lines.append(enriched)
    
    if channel_name and len(messages) > 1:
        header = f"Conversation in #{channel_name}:\n"
        return header + "\n".join(lines)
    
    return "\n".join(lines)
```

### Step 5: Complete Celery Task

```python
# apps/bot/src/tasks.py (updated)
"""
Celery Tasks for Message Processing

Handles async indexing pipeline: Postgres → Embedding → Qdrant
"""

import sys
from pathlib import Path
from datetime import datetime
from uuid import uuid4
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from celery import Celery
from sqlalchemy import create_engine, text

from apps.bot.src.config import get_bot_settings
from packages.shared.python.models import IndexTaskPayload, DeleteTaskPayload


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
    task_time_limit=300,
    task_acks_late=True,  # Reliability: ack after completion
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)


def get_db_engine():
    """Get sync database engine."""
    settings = get_bot_settings()
    sync_url = settings.database_url.replace("+asyncpg", "")
    return create_engine(sync_url, pool_pre_ping=True)


@celery_app.task(
    bind=True,
    name="index_session",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)
def index_session(
    self,
    guild_id: int,
    channel_id: int,
    channel_name: str,
    session_id: str,
    message_ids: list[int],
    start_time: str,
    end_time: str,
) -> dict:
    """
    Index a message session to Qdrant.
    
    Pipeline:
    1. Fetch messages from Postgres
    2. Enrich with metadata
    3. Generate embedding
    4. Upsert to Qdrant
    5. Update session record with qdrant_point_id
    """
    import asyncio
    from apps.api.src.services.embedding_service import generate_embedding
    from apps.api.src.services.enrichment_service import enrich_session
    from apps.api.src.services.qdrant_service import qdrant_service
    
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
    
    enriched_text = enrich_session(messages, channel_name=channel_name)
    
    # 3. Generate embedding
    embedding = generate_embedding(enriched_text)
    
    # 4. Upsert to Qdrant
    author_ids = list(set(row.author_id for row in rows if hasattr(row, 'author_id')))
    
    success = asyncio.run(qdrant_service.upsert_session(
        session_id=session_id,
        guild_id=guild_id,
        channel_id=channel_id,
        embedding=embedding,
        message_ids=message_ids,
        content_preview=enriched_text[:500],
        start_time=start_time,
        end_time=end_time,
        author_ids=author_ids,
    ))
    
    if not success:
        raise Exception("Qdrant upsert failed")
    
    # 5. Update session record
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE message_sessions
            SET qdrant_point_id = :point_id
            WHERE id = :session_id
        """), {"point_id": session_id, "session_id": session_id})
        conn.commit()
    
    return {
        "status": "success",
        "session_id": session_id,
        "message_count": len(message_ids),
        "embedding_size": len(embedding),
    }


@celery_app.task(
    bind=True,
    name="delete_session_vector",
    max_retries=3,
)
def delete_session_vector(
    self,
    guild_id: int,
    session_id: str,
) -> dict:
    """Delete a session vector from Qdrant."""
    import asyncio
    from apps.api.src.services.qdrant_service import qdrant_service
    
    success = asyncio.run(qdrant_service.delete_by_session_id(session_id))
    
    return {
        "status": "success" if success else "not_found",
        "session_id": session_id,
    }


@celery_app.task(
    bind=True,
    name="delete_message_vectors",
    max_retries=3,
)
def delete_message_vectors(
    self,
    guild_id: int,
    message_ids: list[int],
) -> dict:
    """
    Delete vectors containing specific message IDs.
    
    Used for "Right to be Forgotten" compliance.
    """
    import asyncio
    from apps.api.src.services.qdrant_service import qdrant_service
    
    deleted = asyncio.run(qdrant_service.delete_by_message_ids(guild_id, message_ids))
    
    return {
        "status": "success",
        "guild_id": guild_id,
        "messages_processed": len(message_ids),
        "sessions_deleted": deleted,
    }


@celery_app.task(bind=True, name="batch_index_channel")
def batch_index_channel(
    self,
    guild_id: int,
    channel_id: int,
    channel_name: str,
    batch_size: int = 100,
) -> dict:
    """
    Batch index all unindexed messages in a channel.
    
    Used for initial backfill or re-indexing.
    """
    from apps.bot.src.sessionizer import sessionize_messages, Message
    
    engine = get_db_engine()
    
    # Fetch unindexed messages
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT m.id, m.content, m.author_id, m.message_timestamp, m.reply_to_id
            FROM messages m
            WHERE m.guild_id = :guild_id
              AND m.channel_id = :channel_id
              AND m.is_deleted = FALSE
              AND m.qdrant_point_id IS NULL
            ORDER BY m.message_timestamp ASC
            LIMIT :limit
        """), {"guild_id": guild_id, "channel_id": channel_id, "limit": batch_size})
        
        rows = result.fetchall()
    
    if not rows:
        return {"status": "complete", "indexed": 0}
    
    # Convert to Message objects for sessionizer
    messages = [
        Message(
            id=row.id,
            channel_id=channel_id,
            author_id=row.author_id,
            content=row.content,
            timestamp=row.message_timestamp,
            reply_to_id=row.reply_to_id,
        )
        for row in rows
    ]
    
    # Sessionize
    sessions = sessionize_messages(messages)
    
    # Queue each session for indexing
    indexed_count = 0
    for session in sessions:
        if len(session.messages) >= 2:  # Skip tiny sessions
            session_id = str(uuid4())
            
            index_session.delay(
                guild_id=guild_id,
                channel_id=channel_id,
                channel_name=channel_name,
                session_id=session_id,
                message_ids=session.message_ids,
                start_time=session.start_time.isoformat(),
                end_time=session.end_time.isoformat(),
            )
            indexed_count += 1
    
    return {
        "status": "processing",
        "messages_found": len(rows),
        "sessions_queued": indexed_count,
    }
```

---

## 5. Integration Points

### Update RAG Agent to Use Real Qdrant Search

```python
# apps/api/src/agents/vector_rag.py (update search_vectors function)

async def search_vectors(
    query: str,
    guild_id: int,
    channel_ids: Optional[list[int]] = None,
    limit: int = 5,
) -> list[dict]:
    """Search Qdrant for relevant content."""
    from apps.api.src.services.embedding_service import generate_embedding
    from apps.api.src.services.qdrant_service import qdrant_service
    
    # Ensure collection exists
    await qdrant_service.ensure_collection()
    
    # Generate query embedding
    query_embedding = generate_embedding(query)
    
    # Search with multi-tenant filter
    results = await qdrant_service.search(
        query_embedding=query_embedding,
        guild_id=guild_id,
        channel_ids=channel_ids,
        limit=limit,
    )
    
    return results
```

---

## 6. Performance Best Practices (2025)

Based on Qdrant documentation and community best practices:

1. **Vector Dimensions**: Use 384-dim models for speed; 768+ for quality
2. **Batch Operations**: Upsert in batches of 100-1000 points
3. **Payload Indexes**: Create indexes on frequently filtered fields
4. **Content Size**: Keep payload < 1KB; store full text elsewhere
5. **HNSW Tuning**: Default `ef_construct` is good; increase for better recall

---

## 7. References

- [Qdrant Python Client](https://python-client.qdrant.tech/)
- [FastEmbed Documentation](https://qdrant.tech/documentation/fastembed/)
- [Qdrant Best Practices](https://www.cohorte.co/blog/a-developers-friendly-guide-to-qdrant-vector-database)
- [Async Qdrant Client](https://python-client.qdrant.tech/qdrant_client.async_qdrant_fastembed)

---

## 8. Checklist

- [ ] Add dependencies: `qdrant-client`, `fastembed`
- [ ] Create `apps/api/src/services/embedding_service.py`
- [ ] Create `apps/api/src/services/qdrant_service.py`
- [ ] Create `apps/api/src/services/enrichment_service.py`
- [ ] Update `apps/bot/src/tasks.py` with real implementation
- [ ] Update `apps/api/src/agents/vector_rag.py` to use new services
- [ ] Add Qdrant collection initialization on API startup
- [ ] Test with real Discord messages
- [ ] Run batch indexing for existing messages
