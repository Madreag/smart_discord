"""
Qdrant Service - Vector database operations with multi-tenant isolation.

INVARIANT: All operations MUST include guild_id in filter/payload.
"""

from typing import Optional, Any
from uuid import UUID

from qdrant_client import QdrantClient
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
    UpdateStatus,
)

from apps.api.src.core.config import get_settings
from apps.api.src.core.llm_factory import get_embedding_model


# Collection configuration
COLLECTION_NAME = "discord_sessions"


def get_vector_size() -> int:
    """Get vector size based on configured embedding model."""
    embedding_model = get_embedding_model()
    return embedding_model.dimension


class QdrantService:
    """Sync Qdrant client wrapper with multi-tenant support."""
    
    def __init__(self):
        self._client: Optional[QdrantClient] = None
        self._collection_initialized = False
    
    def get_client(self) -> QdrantClient:
        """Get or create Qdrant client."""
        if self._client is None:
            settings = get_settings()
            self._client = QdrantClient(
                url=settings.qdrant_url,
                timeout=30.0,
            )
        return self._client
    
    def ensure_collection(self) -> None:
        """Create collection and indexes if they don't exist."""
        if self._collection_initialized:
            return
            
        client = self.get_client()
        vector_size = get_vector_size()
        
        collections = client.get_collections()
        existing = [c.name for c in collections.collections]
        
        if COLLECTION_NAME not in existing:
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=Distance.COSINE,
                ),
                optimizers_config=models.OptimizersConfigDiff(
                    indexing_threshold=10000,
                ),
            )
            
            # Create payload indexes for efficient filtering
            client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name="guild_id",
                field_schema=PayloadSchemaType.INTEGER,
            )
            client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name="channel_id",
                field_schema=PayloadSchemaType.INTEGER,
            )
            
            print(f"Created Qdrant collection: {COLLECTION_NAME} with {vector_size} dimensions")
        
        self._collection_initialized = True
    
    def upsert_session(
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
            embedding: Vector embedding
            message_ids: List of message IDs in session
            content_preview: Truncated content for display
            start_time: ISO timestamp
            end_time: ISO timestamp
            author_ids: List of author IDs in session
            
        Returns:
            True if successful
        """
        self.ensure_collection()
        client = self.get_client()
        
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
        
        result = client.upsert(
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
        
        return result.status == UpdateStatus.COMPLETED
    
    def upsert_batch(self, points: list[dict]) -> bool:
        """
        Batch upsert multiple sessions.
        
        Args:
            points: List of dicts with keys: id, vector, payload
                
        Returns:
            True if successful
        """
        self.ensure_collection()
        client = self.get_client()
        
        qdrant_points = [
            PointStruct(
                id=p["id"],
                vector=p["vector"],
                payload=p["payload"],
            )
            for p in points
        ]
        
        result = client.upsert(
            collection_name=COLLECTION_NAME,
            points=qdrant_points,
            wait=True,
        )
        
        return result.status == UpdateStatus.COMPLETED
    
    def search(
        self,
        query_embedding: list[float],
        guild_id: int,
        channel_ids: Optional[list[int]] = None,
        limit: int = 5,
        score_threshold: float = 0.2,
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
        self.ensure_collection()
        client = self.get_client()
        
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
        
        results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_embedding,
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
            for r in results.points
        ]
    
    def delete_by_session_id(self, session_id: str) -> bool:
        """Delete a session by ID."""
        client = self.get_client()
        
        result = client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=models.PointIdsList(
                points=[session_id],
            ),
        )
        
        return result.status == UpdateStatus.COMPLETED
    
    def delete_by_guild(self, guild_id: int) -> bool:
        """Delete all sessions for a guild."""
        client = self.get_client()
        
        result = client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=models.FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="guild_id",
                            match=MatchValue(value=guild_id),
                        ),
                    ]
                )
            ),
        )
        
        return result.status == UpdateStatus.COMPLETED
    
    def get_collection_info(self) -> dict:
        """Get collection statistics."""
        self.ensure_collection()
        client = self.get_client()
        
        info = client.get_collection(COLLECTION_NAME)
        return {
            "name": COLLECTION_NAME,
            "vectors_count": getattr(info, 'vectors_count', None) or info.points_count,
            "points_count": info.points_count,
            "status": info.status.value if hasattr(info.status, 'value') else str(info.status),
        }


# Global service instance
qdrant_service = QdrantService()
