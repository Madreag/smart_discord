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
    SparseVectorParams,
    SparseIndexParams,
    SparseVector,
    Prefetch,
    FusionQuery,
    Fusion,
    NamedVector,
    NamedSparseVector,
)

from apps.api.src.core.config import get_settings
from apps.api.src.core.llm_factory import get_embedding_model


# Collection configuration
COLLECTION_NAME = "discord_sessions"
HYBRID_COLLECTION_NAME = "discord_sessions_hybrid"

# Named vector configuration
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"


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
    
    def upsert_with_metadata(
        self,
        point_id: str,
        vector: list[float],
        payload: dict,
    ) -> bool:
        """
        Upsert a single point with custom payload (for document chunks).
        
        Args:
            point_id: Unique point ID
            vector: Embedding vector
            payload: Custom payload with source_type, etc.
            
        Returns:
            True if successful
        """
        self.ensure_collection()
        client = self.get_client()
        
        result = client.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                ),
            ],
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
        source_types: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Search for similar vectors with multi-tenant filtering.
        
        Args:
            query_embedding: Query vector
            guild_id: Guild ID (REQUIRED for isolation)
            channel_ids: Optional channel filter
            limit: Max results
            score_threshold: Minimum similarity score
            source_types: Optional filter for source types (e.g., ['pdf', 'markdown'])
            
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
        
        # Filter by source_type if specified (for document queries)
        if source_types:
            must_conditions.append(
                FieldCondition(
                    key="source_type",
                    match=MatchAny(any=source_types),
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
    
    def delete_sessions_containing_messages(
        self,
        guild_id: int,
        message_ids: list[int],
    ) -> dict:
        """
        Delete all sessions that contain any of the specified message IDs.
        
        This is used for "Right to be Forgotten" compliance - when a message
        is deleted, all sessions containing that message must be removed
        from the vector database to prevent the deleted content from
        appearing in RAG responses.
        
        Args:
            guild_id: Guild ID for multi-tenant filtering
            message_ids: List of message IDs that were deleted
            
        Returns:
            Dict with deleted_count and session_ids
        """
        client = self.get_client()
        deleted_session_ids = []
        
        try:
            # Scroll through all sessions for this guild and find ones containing deleted messages
            # This is necessary because Qdrant doesn't support "array contains any" filtering
            offset = None
            batch_size = 100
            
            while True:
                results = client.scroll(
                    collection_name=COLLECTION_NAME,
                    scroll_filter=Filter(
                        must=[
                            FieldCondition(
                                key="guild_id",
                                match=MatchValue(value=guild_id),
                            ),
                        ]
                    ),
                    limit=batch_size,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                
                points, next_offset = results
                
                if not points:
                    break
                
                # Check each session for deleted message IDs
                for point in points:
                    payload = point.payload or {}
                    session_message_ids = payload.get("message_ids", [])
                    
                    # If any deleted message is in this session, mark for deletion
                    if any(mid in session_message_ids for mid in message_ids):
                        deleted_session_ids.append(str(point.id))
                
                if next_offset is None:
                    break
                offset = next_offset
            
            # Delete all found sessions
            if deleted_session_ids:
                client.delete(
                    collection_name=COLLECTION_NAME,
                    points_selector=models.PointIdsList(
                        points=deleted_session_ids,
                    ),
                )
                print(f"[QDRANT] Deleted {len(deleted_session_ids)} sessions containing deleted messages")
            
            return {
                "deleted_count": len(deleted_session_ids),
                "session_ids": deleted_session_ids,
            }
            
        except Exception as e:
            print(f"[QDRANT ERROR] delete_sessions_containing_messages: {e}")
            return {"deleted_count": 0, "session_ids": [], "error": str(e)}
    
    def get_sessions_by_message_ids(
        self,
        guild_id: int,
        message_ids: list[int],
    ) -> list[dict]:
        """
        Find all sessions containing any of the specified message IDs.
        
        Useful for checking if a message is indexed before deletion.
        
        Args:
            guild_id: Guild ID for filtering
            message_ids: Message IDs to search for
            
        Returns:
            List of session dicts with id and message_ids
        """
        client = self.get_client()
        found_sessions = []
        
        try:
            offset = None
            batch_size = 100
            
            while True:
                results = client.scroll(
                    collection_name=COLLECTION_NAME,
                    scroll_filter=Filter(
                        must=[
                            FieldCondition(
                                key="guild_id",
                                match=MatchValue(value=guild_id),
                            ),
                        ]
                    ),
                    limit=batch_size,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                
                points, next_offset = results
                
                if not points:
                    break
                
                for point in points:
                    payload = point.payload or {}
                    session_message_ids = payload.get("message_ids", [])
                    
                    if any(mid in session_message_ids for mid in message_ids):
                        found_sessions.append({
                            "session_id": str(point.id),
                            "message_ids": session_message_ids,
                            "channel_id": payload.get("channel_id"),
                        })
                
                if next_offset is None:
                    break
                offset = next_offset
            
            return found_sessions
            
        except Exception as e:
            print(f"[QDRANT ERROR] get_sessions_by_message_ids: {e}")
            return []
    
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
    
    # ==================== HYBRID SEARCH METHODS ====================
    
    def ensure_hybrid_collection(self) -> None:
        """
        Create hybrid collection with named dense + sparse vectors.
        
        This collection supports:
        - Dense vectors (semantic similarity)
        - Sparse vectors (BM25 keyword matching)
        - RRF fusion for hybrid search
        """
        client = self.get_client()
        vector_size = get_vector_size()
        
        collections = client.get_collections()
        existing = [c.name for c in collections.collections]
        
        if HYBRID_COLLECTION_NAME not in existing:
            client.create_collection(
                collection_name=HYBRID_COLLECTION_NAME,
                vectors_config={
                    DENSE_VECTOR_NAME: VectorParams(
                        size=vector_size,
                        distance=Distance.COSINE,
                    ),
                },
                sparse_vectors_config={
                    SPARSE_VECTOR_NAME: SparseVectorParams(
                        index=SparseIndexParams(
                            on_disk=False,
                        ),
                    ),
                },
                optimizers_config=models.OptimizersConfigDiff(
                    indexing_threshold=10000,
                ),
            )
            
            # Create payload indexes for efficient filtering
            client.create_payload_index(
                collection_name=HYBRID_COLLECTION_NAME,
                field_name="guild_id",
                field_schema=PayloadSchemaType.INTEGER,
            )
            client.create_payload_index(
                collection_name=HYBRID_COLLECTION_NAME,
                field_name="channel_id",
                field_schema=PayloadSchemaType.INTEGER,
            )
            client.create_payload_index(
                collection_name=HYBRID_COLLECTION_NAME,
                field_name="source_type",
                field_schema=PayloadSchemaType.KEYWORD,
            )
            
            print(f"[HYBRID] Created collection: {HYBRID_COLLECTION_NAME} with dense ({vector_size}D) + sparse vectors")
    
    def upsert_hybrid(
        self,
        point_id: str,
        dense_vector: list[float],
        sparse_indices: list[int],
        sparse_values: list[float],
        payload: dict,
    ) -> bool:
        """
        Upsert a point with both dense and sparse vectors.
        
        Args:
            point_id: Unique point ID
            dense_vector: Dense embedding vector
            sparse_indices: BM25 sparse vector indices
            sparse_values: BM25 sparse vector values
            payload: Metadata payload (must include guild_id)
            
        Returns:
            True if successful
        """
        self.ensure_hybrid_collection()
        client = self.get_client()
        
        # Build vector dict with named vectors
        vectors = {
            DENSE_VECTOR_NAME: dense_vector,
        }
        
        # Only add sparse vector if we have data
        if sparse_indices and sparse_values:
            vectors[SPARSE_VECTOR_NAME] = SparseVector(
                indices=sparse_indices,
                values=sparse_values,
            )
        
        result = client.upsert(
            collection_name=HYBRID_COLLECTION_NAME,
            points=[
                PointStruct(
                    id=point_id,
                    vector=vectors,
                    payload=payload,
                ),
            ],
            wait=True,
        )
        
        return result.status == UpdateStatus.COMPLETED
    
    def upsert_hybrid_batch(self, points: list[dict]) -> bool:
        """
        Batch upsert points with hybrid vectors.
        
        Args:
            points: List of dicts with keys:
                - id: Point ID
                - dense_vector: Dense embedding
                - sparse_indices: BM25 indices
                - sparse_values: BM25 values
                - payload: Metadata
                
        Returns:
            True if successful
        """
        self.ensure_hybrid_collection()
        client = self.get_client()
        
        qdrant_points = []
        for p in points:
            vectors = {
                DENSE_VECTOR_NAME: p["dense_vector"],
            }
            if p.get("sparse_indices") and p.get("sparse_values"):
                vectors[SPARSE_VECTOR_NAME] = SparseVector(
                    indices=p["sparse_indices"],
                    values=p["sparse_values"],
                )
            
            qdrant_points.append(
                PointStruct(
                    id=p["id"],
                    vector=vectors,
                    payload=p["payload"],
                )
            )
        
        result = client.upsert(
            collection_name=HYBRID_COLLECTION_NAME,
            points=qdrant_points,
            wait=True,
        )
        
        return result.status == UpdateStatus.COMPLETED
    
    def hybrid_search(
        self,
        query_dense: list[float],
        query_sparse_indices: list[int],
        query_sparse_values: list[float],
        guild_id: int,
        channel_ids: Optional[list[int]] = None,
        limit: int = 5,
        score_threshold: float = 0.0,
        source_types: Optional[list[str]] = None,
        dense_weight: float = 0.7,
        sparse_weight: float = 0.3,
    ) -> list[dict]:
        """
        Hybrid search combining dense (semantic) and sparse (BM25) vectors.
        
        Uses Reciprocal Rank Fusion (RRF) to combine results from both
        dense and sparse searches.
        
        Args:
            query_dense: Dense query embedding
            query_sparse_indices: BM25 sparse indices
            query_sparse_values: BM25 sparse values
            guild_id: Guild ID for filtering (REQUIRED)
            channel_ids: Optional channel filter
            limit: Max results
            score_threshold: Minimum score threshold
            source_types: Optional source type filter
            dense_weight: Weight for dense results (default 0.7)
            sparse_weight: Weight for sparse results (default 0.3)
            
        Returns:
            List of results with id, score, payload
        """
        self.ensure_hybrid_collection()
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
        
        if source_types:
            must_conditions.append(
                FieldCondition(
                    key="source_type",
                    match=MatchAny(any=source_types),
                )
            )
        
        query_filter = Filter(must=must_conditions)
        
        # Build prefetch queries for RRF fusion
        prefetch_queries = []
        
        # Dense (semantic) search prefetch
        prefetch_queries.append(
            Prefetch(
                query=query_dense,
                using=DENSE_VECTOR_NAME,
                limit=limit * 3,  # Oversample for fusion
                filter=query_filter,
            )
        )
        
        # Sparse (BM25) search prefetch - only if we have sparse data
        if query_sparse_indices and query_sparse_values:
            prefetch_queries.append(
                Prefetch(
                    query=SparseVector(
                        indices=query_sparse_indices,
                        values=query_sparse_values,
                    ),
                    using=SPARSE_VECTOR_NAME,
                    limit=limit * 3,
                    filter=query_filter,
                )
            )
        
        # Execute hybrid search with RRF fusion
        try:
            results = client.query_points(
                collection_name=HYBRID_COLLECTION_NAME,
                prefetch=prefetch_queries,
                query=FusionQuery(fusion=Fusion.RRF),
                limit=limit,
                with_payload=True,
            )
            
            return [
                {
                    "id": str(r.id),
                    "score": r.score,
                    "payload": r.payload,
                }
                for r in results.points
                if r.score >= score_threshold
            ]
            
        except Exception as e:
            print(f"[HYBRID] Search error: {e}")
            # Fallback to dense-only search
            return self._dense_only_search(
                query_dense, guild_id, channel_ids, limit, score_threshold, source_types
            )
    
    def _dense_only_search(
        self,
        query_dense: list[float],
        guild_id: int,
        channel_ids: Optional[list[int]] = None,
        limit: int = 5,
        score_threshold: float = 0.2,
        source_types: Optional[list[str]] = None,
    ) -> list[dict]:
        """Fallback dense-only search on hybrid collection."""
        client = self.get_client()
        
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
        
        if source_types:
            must_conditions.append(
                FieldCondition(
                    key="source_type",
                    match=MatchAny(any=source_types),
                )
            )
        
        results = client.query_points(
            collection_name=HYBRID_COLLECTION_NAME,
            query=query_dense,
            using=DENSE_VECTOR_NAME,
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
    
    def get_hybrid_collection_info(self) -> dict:
        """Get hybrid collection statistics."""
        self.ensure_hybrid_collection()
        client = self.get_client()
        
        info = client.get_collection(HYBRID_COLLECTION_NAME)
        return {
            "name": HYBRID_COLLECTION_NAME,
            "vectors_count": getattr(info, 'vectors_count', None) or info.points_count,
            "points_count": info.points_count,
            "status": info.status.value if hasattr(info.status, 'value') else str(info.status),
            "hybrid_enabled": True,
        }
    
    def migrate_to_hybrid(self, batch_size: int = 100) -> dict:
        """
        Migrate existing points from legacy collection to hybrid collection.
        
        This re-indexes all points with both dense and sparse vectors.
        
        Args:
            batch_size: Number of points to process per batch
            
        Returns:
            Dict with migration stats
        """
        from apps.api.src.services.hybrid_embedding import get_hybrid_embedding_model
        
        client = self.get_client()
        self.ensure_hybrid_collection()
        
        hybrid_model = get_hybrid_embedding_model()
        migrated = 0
        errors = 0
        offset = None
        
        print(f"[HYBRID] Starting migration from {COLLECTION_NAME} to {HYBRID_COLLECTION_NAME}")
        
        while True:
            # Scroll through legacy collection
            results = client.scroll(
                collection_name=COLLECTION_NAME,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            
            points, next_offset = results
            
            if not points:
                break
            
            # Process batch
            hybrid_points = []
            for point in points:
                try:
                    payload = point.payload or {}
                    content = payload.get("content", "")
                    
                    # Get dense vector from existing point
                    dense_vector = point.vector if isinstance(point.vector, list) else list(point.vector)
                    
                    # Generate sparse embedding for content
                    if content and hybrid_model.sparse_enabled:
                        hybrid_emb = hybrid_model.embed_document(content)
                        sparse_indices = hybrid_emb.sparse_indices
                        sparse_values = hybrid_emb.sparse_values
                    else:
                        sparse_indices = []
                        sparse_values = []
                    
                    hybrid_points.append({
                        "id": str(point.id),
                        "dense_vector": dense_vector,
                        "sparse_indices": sparse_indices,
                        "sparse_values": sparse_values,
                        "payload": payload,
                    })
                    
                except Exception as e:
                    print(f"[HYBRID] Error processing point {point.id}: {e}")
                    errors += 1
            
            # Upsert batch to hybrid collection
            if hybrid_points:
                self.upsert_hybrid_batch(hybrid_points)
                migrated += len(hybrid_points)
                print(f"[HYBRID] Migrated {migrated} points...")
            
            if next_offset is None:
                break
            offset = next_offset
        
        print(f"[HYBRID] Migration complete: {migrated} points migrated, {errors} errors")
        return {
            "migrated": migrated,
            "errors": errors,
        }


# Global service instance
qdrant_service = QdrantService()
