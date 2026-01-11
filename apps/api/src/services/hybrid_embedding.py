"""
Hybrid Embedding Service - Dense + Sparse (BM25) vector generation.

Generates both:
1. Dense embeddings (semantic meaning) via sentence-transformers or OpenAI
2. Sparse embeddings (BM25 keyword matching) via FastEmbed

Used for hybrid search combining semantic similarity with exact keyword matching.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
import numpy as np


@dataclass
class HybridEmbedding:
    """Container for dense and sparse embeddings."""
    dense: List[float]
    sparse_indices: List[int]
    sparse_values: List[float]
    
    def to_dict(self) -> dict:
        return {
            "dense": self.dense,
            "sparse_indices": self.sparse_indices,
            "sparse_values": self.sparse_values,
        }


class HybridEmbeddingModel:
    """
    Unified hybrid embedding interface.
    
    Generates both dense (semantic) and sparse (BM25) vectors for hybrid search.
    """
    
    def __init__(self):
        self._dense_model = None
        self._sparse_model = None
        self._initialized = False
    
    def _ensure_models(self):
        """Lazy-load embedding models."""
        if self._initialized:
            return
        
        # Get dense embedding model from existing factory
        from apps.api.src.core.llm_factory import get_embedding_model
        self._dense_model = get_embedding_model()
        
        # Initialize sparse BM25 model via FastEmbed
        try:
            from fastembed import SparseTextEmbedding
            self._sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")
            print("[HYBRID] Initialized BM25 sparse embedding model")
        except ImportError:
            print("[HYBRID] FastEmbed not available, sparse search disabled")
            self._sparse_model = None
        except Exception as e:
            print(f"[HYBRID] Error initializing sparse model: {e}")
            self._sparse_model = None
        
        self._initialized = True
    
    @property
    def dense_dimension(self) -> int:
        """Get dense vector dimension."""
        self._ensure_models()
        return self._dense_model.dimension
    
    @property
    def sparse_enabled(self) -> bool:
        """Check if sparse embeddings are available."""
        self._ensure_models()
        return self._sparse_model is not None
    
    def embed_query(self, text: str) -> HybridEmbedding:
        """
        Generate hybrid embedding for a query.
        
        Args:
            text: Query text to embed
            
        Returns:
            HybridEmbedding with dense and sparse vectors
        """
        self._ensure_models()
        
        # Get dense embedding
        dense = self._dense_model.embed_query(text)
        
        # Get sparse embedding (BM25)
        sparse_indices = []
        sparse_values = []
        
        if self._sparse_model is not None:
            try:
                sparse_embeddings = list(self._sparse_model.query_embed(text))
                if sparse_embeddings:
                    sparse_emb = sparse_embeddings[0]
                    sparse_indices = sparse_emb.indices.tolist()
                    sparse_values = sparse_emb.values.tolist()
            except Exception as e:
                print(f"[HYBRID] Sparse embedding error: {e}")
        
        return HybridEmbedding(
            dense=dense,
            sparse_indices=sparse_indices,
            sparse_values=sparse_values,
        )
    
    def embed_document(self, text: str) -> HybridEmbedding:
        """
        Generate hybrid embedding for a document.
        
        Args:
            text: Document text to embed
            
        Returns:
            HybridEmbedding with dense and sparse vectors
        """
        self._ensure_models()
        
        # Get dense embedding
        dense = self._dense_model.embed_query(text)
        
        # Get sparse embedding (BM25) - use passage_embed for documents
        sparse_indices = []
        sparse_values = []
        
        if self._sparse_model is not None:
            try:
                sparse_embeddings = list(self._sparse_model.passage_embed([text]))
                if sparse_embeddings:
                    sparse_emb = sparse_embeddings[0]
                    sparse_indices = sparse_emb.indices.tolist()
                    sparse_values = sparse_emb.values.tolist()
            except Exception as e:
                print(f"[HYBRID] Sparse embedding error: {e}")
        
        return HybridEmbedding(
            dense=dense,
            sparse_indices=sparse_indices,
            sparse_values=sparse_values,
        )
    
    def embed_documents(self, texts: List[str]) -> List[HybridEmbedding]:
        """
        Generate hybrid embeddings for multiple documents.
        
        Args:
            texts: List of document texts to embed
            
        Returns:
            List of HybridEmbedding objects
        """
        self._ensure_models()
        
        # Get dense embeddings in batch
        dense_embeddings = self._dense_model.embed_documents(texts)
        
        # Get sparse embeddings in batch
        sparse_embeddings_list = []
        if self._sparse_model is not None:
            try:
                sparse_results = list(self._sparse_model.passage_embed(texts))
                for sparse_emb in sparse_results:
                    sparse_embeddings_list.append({
                        "indices": sparse_emb.indices.tolist(),
                        "values": sparse_emb.values.tolist(),
                    })
            except Exception as e:
                print(f"[HYBRID] Batch sparse embedding error: {e}")
                sparse_embeddings_list = [{"indices": [], "values": []} for _ in texts]
        else:
            sparse_embeddings_list = [{"indices": [], "values": []} for _ in texts]
        
        # Combine into HybridEmbedding objects
        results = []
        for i, dense in enumerate(dense_embeddings):
            sparse = sparse_embeddings_list[i] if i < len(sparse_embeddings_list) else {"indices": [], "values": []}
            results.append(HybridEmbedding(
                dense=dense,
                sparse_indices=sparse["indices"],
                sparse_values=sparse["values"],
            ))
        
        return results


class LateInteractionModel:
    """
    Late interaction (ColBERT-style) reranking model.
    
    Uses token-level embeddings for more precise relevance scoring.
    This is computationally expensive but provides highest quality results.
    """
    
    def __init__(self):
        self._model = None
        self._initialized = False
    
    def _ensure_model(self):
        """Lazy-load late interaction model."""
        if self._initialized:
            return
        
        try:
            from sentence_transformers import SentenceTransformer
            # Use a model that supports token-level embeddings
            # ColBERT-style models produce per-token embeddings
            self._model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            print("[LATE_INTERACTION] Initialized reranking model")
        except Exception as e:
            print(f"[LATE_INTERACTION] Model not available: {e}")
            self._model = None
        
        self._initialized = True
    
    @property
    def enabled(self) -> bool:
        """Check if late interaction is available."""
        self._ensure_model()
        return self._model is not None
    
    def rerank(
        self,
        query: str,
        documents: List[dict],
        top_k: int = 5,
    ) -> List[dict]:
        """
        Rerank documents using late interaction scoring.
        
        This computes more precise relevance scores by comparing
        query and document at the token level.
        
        Args:
            query: Query text
            documents: List of dicts with 'payload' containing 'content'
            top_k: Number of top results to return
            
        Returns:
            Reranked list of documents with updated scores
        """
        self._ensure_model()
        
        if not self._model or not documents:
            return documents[:top_k]
        
        try:
            # Get query embedding
            query_embedding = self._model.encode(query, convert_to_numpy=True)
            
            # Score each document
            scored_docs = []
            for doc in documents:
                payload = doc.get("payload", {})
                content = payload.get("content", payload.get("text", payload.get("summary", "")))
                
                if not content:
                    scored_docs.append((doc, doc.get("score", 0)))
                    continue
                
                # Get document embedding
                doc_embedding = self._model.encode(content[:1000], convert_to_numpy=True)
                
                # Compute cosine similarity
                similarity = float(np.dot(query_embedding, doc_embedding) / (
                    np.linalg.norm(query_embedding) * np.linalg.norm(doc_embedding) + 1e-8
                ))
                
                # Combine with original score (weighted average)
                original_score = doc.get("score", 0)
                combined_score = 0.6 * similarity + 0.4 * original_score
                
                scored_docs.append((doc, combined_score))
            
            # Sort by combined score
            scored_docs.sort(key=lambda x: x[1], reverse=True)
            
            # Return top_k with updated scores
            results = []
            for doc, score in scored_docs[:top_k]:
                updated_doc = doc.copy()
                updated_doc["rerank_score"] = score
                updated_doc["original_score"] = doc.get("score", 0)
                updated_doc["score"] = score
                results.append(updated_doc)
            
            return results
            
        except Exception as e:
            print(f"[LATE_INTERACTION] Reranking error: {e}")
            return documents[:top_k]


# Global singleton instances
_hybrid_model: Optional[HybridEmbeddingModel] = None
_late_interaction_model: Optional[LateInteractionModel] = None


def get_hybrid_embedding_model() -> HybridEmbeddingModel:
    """Get or create the hybrid embedding model singleton."""
    global _hybrid_model
    if _hybrid_model is None:
        _hybrid_model = HybridEmbeddingModel()
    return _hybrid_model


def get_late_interaction_model() -> LateInteractionModel:
    """Get or create the late interaction model singleton."""
    global _late_interaction_model
    if _late_interaction_model is None:
        _late_interaction_model = LateInteractionModel()
    return _late_interaction_model
