"""
DM Memory Agent: RAG-based Long-term Memory for Direct Messages

Stores conversation history in PostgreSQL and Qdrant for semantic retrieval.
Enables the bot to remember important information from past conversations.
"""

import sys
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone
import uuid

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from sqlalchemy import create_engine, text


# Embedding model for semantic search
_embedding_model = None

def get_embedding_model():
    """Get or create the embedding model."""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
    return _embedding_model


def get_db_engine():
    """Get database engine."""
    from apps.api.src.core.config import get_settings
    settings = get_settings()
    sync_url = settings.database_url.replace("+asyncpg", "")
    return create_engine(sync_url, pool_pre_ping=True)


def get_qdrant_client():
    """Get Qdrant client."""
    from qdrant_client import QdrantClient
    from apps.api.src.core.config import get_settings
    settings = get_settings()
    return QdrantClient(url=settings.qdrant_url)


def ensure_dm_collection():
    """Ensure the DM memory collection exists in Qdrant."""
    try:
        from qdrant_client.models import Distance, VectorParams
        client = get_qdrant_client()
        
        collections = client.get_collections().collections
        collection_names = [c.name for c in collections]
        
        if "dm_memory" not in collection_names:
            client.create_collection(
                collection_name="dm_memory",
                vectors_config=VectorParams(size=384, distance=Distance.COSINE),
            )
            print("Created dm_memory collection in Qdrant")
        return True
    except Exception as e:
        print(f"Qdrant not available: {e}")
        return False


def store_dm_message(
    user_id: int,
    role: str,
    content: str,
) -> Optional[int]:
    """
    Store a DM message in PostgreSQL and optionally embed in Qdrant.
    
    Returns the message ID if successful.
    """
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            result = conn.execute(text("""
                INSERT INTO dm_messages (user_id, role, content, message_timestamp)
                VALUES (:user_id, :role, :content, NOW())
                RETURNING id
            """), {
                "user_id": user_id,
                "role": role,
                "content": content,
            })
            message_id = result.scalar()
            conn.commit()
            
            # Try to embed in Qdrant (if available)
            try:
                embed_dm_message(message_id, user_id, role, content)
            except Exception:
                pass  # Qdrant embedding is optional
            
            return message_id
    except Exception as e:
        print(f"Error storing DM message: {e}")
        return None


def embed_dm_message(
    message_id: int,
    user_id: int,
    role: str,
    content: str,
) -> bool:
    """Embed a DM message in Qdrant for semantic retrieval."""
    try:
        from qdrant_client.models import PointStruct
        
        if not ensure_dm_collection():
            return False
        
        model = get_embedding_model()
        client = get_qdrant_client()
        
        # Create embedding
        embedding = model.encode(content).tolist()
        
        # Generate UUID for the point
        point_id = str(uuid.uuid4())
        
        # Store in Qdrant with user_id for filtering
        client.upsert(
            collection_name="dm_memory",
            points=[
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "message_id": message_id,
                        "user_id": user_id,
                        "role": role,
                        "content": content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            ]
        )
        
        # Update PostgreSQL with point ID
        engine = get_db_engine()
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE dm_messages 
                SET qdrant_point_id = :point_id, indexed_at = NOW()
                WHERE id = :message_id
            """), {
                "point_id": point_id,
                "message_id": message_id,
            })
            conn.commit()
        
        return True
    except Exception as e:
        print(f"Error embedding DM message: {e}")
        return False


def retrieve_relevant_context(
    user_id: int,
    query: str,
    limit: int = 5,
) -> list[dict]:
    """
    Retrieve relevant past conversation context for a user.
    
    Uses semantic search to find relevant past messages.
    """
    try:
        if not ensure_dm_collection():
            return []
        
        model = get_embedding_model()
        client = get_qdrant_client()
        
        # Create query embedding
        query_embedding = model.encode(query).tolist()
        
        # Search with user_id filter
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        results = client.search(
            collection_name="dm_memory",
            query_vector=query_embedding,
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="user_id",
                        match=MatchValue(value=user_id),
                    )
                ]
            ),
            limit=limit,
            score_threshold=0.3,  # Only return reasonably relevant results
        )
        
        return [
            {
                "role": r.payload.get("role"),
                "content": r.payload.get("content"),
                "score": r.score,
                "timestamp": r.payload.get("timestamp"),
            }
            for r in results
        ]
    except Exception as e:
        print(f"Error retrieving context: {e}")
        return []


def get_user_server_context(
    user_id: int,
    query: str,
    limit: int = 5,
) -> list[dict]:
    """
    Retrieve relevant server channel messages for a user.
    
    Searches messages the user sent in server channels for context.
    """
    try:
        model = get_embedding_model()
        query_embedding = model.encode(query).tolist()
        
        # Search user's server messages in database
        engine = get_db_engine()
        with engine.connect() as conn:
            # Get recent messages from the user in server channels
            result = conn.execute(text("""
                SELECT m.content, m.message_timestamp, c.name as channel_name
                FROM messages m
                JOIN channels c ON m.channel_id = c.id
                WHERE m.author_id = :user_id 
                  AND m.is_deleted = FALSE
                  AND m.content != ''
                ORDER BY m.message_timestamp DESC
                LIMIT 100
            """), {"user_id": user_id})
            
            messages = [
                {
                    "content": row[0],
                    "timestamp": row[1],
                    "channel": row[2],
                }
                for row in result.fetchall()
            ]
        
        if not messages:
            return []
        
        # Score messages by semantic similarity
        import math
        scored = []
        for msg in messages:
            msg_embedding = model.encode(msg["content"]).tolist()
            # Proper cosine similarity with normalization
            dot_product = sum(a * b for a, b in zip(query_embedding, msg_embedding))
            norm_q = math.sqrt(sum(a * a for a in query_embedding))
            norm_m = math.sqrt(sum(b * b for b in msg_embedding))
            score = dot_product / (norm_q * norm_m) if norm_q and norm_m else 0
            if score > 0.15:  # Lower threshold for cross-context
                scored.append({
                    "content": msg["content"],
                    "channel": msg["channel"],
                    "score": score,
                    "source": "server",
                })
        
        # Sort by score and return top results
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]
        
    except Exception as e:
        print(f"Error getting server context: {e}")
        return []


def get_recent_messages(
    user_id: int,
    limit: int = 10,
) -> list[dict]:
    """Get recent messages from PostgreSQL for a user."""
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT role, content, message_timestamp
                FROM dm_messages
                WHERE user_id = :user_id
                ORDER BY message_timestamp DESC
                LIMIT :limit
            """), {
                "user_id": user_id,
                "limit": limit,
            })
            
            messages = [
                {"role": row[0], "content": row[1], "timestamp": row[2]}
                for row in result.fetchall()
            ]
            
            # Return in chronological order
            return list(reversed(messages))
    except Exception as e:
        print(f"Error getting recent messages: {e}")
        return []
