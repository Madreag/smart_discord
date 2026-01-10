"""
Semantic Chunker - Topic-aware message grouping.

Splits messages into chunks based on semantic similarity rather than just time gaps.
Uses local embeddings for cost-free processing.
"""

import numpy as np
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SemanticChunk:
    """A semantically coherent group of messages."""
    messages: list[dict]
    start_index: int
    end_index: int
    avg_similarity: float
    
    @property
    def message_ids(self) -> list[int]:
        return [m.get("id") for m in self.messages if m.get("id")]
    
    @property
    def start_time(self) -> Optional[datetime]:
        if self.messages and self.messages[0].get("timestamp"):
            ts = self.messages[0]["timestamp"]
            return ts if isinstance(ts, datetime) else None
        return None
    
    @property
    def end_time(self) -> Optional[datetime]:
        if self.messages and self.messages[-1].get("timestamp"):
            ts = self.messages[-1]["timestamp"]
            return ts if isinstance(ts, datetime) else None
        return None


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Calculate cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def calculate_similarities(embeddings: list[list[float]]) -> list[float]:
    """
    Calculate cosine similarity between consecutive embeddings.
    
    Returns list of N-1 similarity scores for N embeddings.
    """
    if len(embeddings) < 2:
        return []
    
    embeddings_np = [np.array(e) for e in embeddings]
    
    similarities = []
    for i in range(len(embeddings_np) - 1):
        sim = cosine_similarity(embeddings_np[i], embeddings_np[i + 1])
        similarities.append(sim)
    
    return similarities


def find_breakpoints(
    similarities: list[float],
    method: str = "percentile",
    threshold: float = 90,
) -> list[int]:
    """
    Find indices where semantic breakpoints occur.
    
    Args:
        similarities: List of similarity scores
        method: "percentile", "std_dev", or "iqr"
        threshold: Threshold value (meaning depends on method)
        
    Returns:
        List of breakpoint indices (split AFTER these indices)
    """
    if len(similarities) < 3:
        return []
    
    similarities_np = np.array(similarities)
    
    if method == "percentile":
        # Split when similarity is in the bottom (100-threshold)%
        cutoff = np.percentile(similarities_np, 100 - threshold)
    elif method == "std_dev":
        # Split when similarity is threshold std devs below mean
        mean = np.mean(similarities_np)
        std = np.std(similarities_np)
        if std == 0:
            return []
        cutoff = mean - (threshold * std)
    elif method == "iqr":
        # Split at statistical outliers
        Q1, Q3 = np.percentile(similarities_np, [25, 75])
        IQR = Q3 - Q1
        cutoff = Q1 - (threshold * IQR)
    else:
        raise ValueError(f"Unknown method: {method}")
    
    # Find indices where similarity drops below cutoff
    breakpoints = []
    for i, sim in enumerate(similarities):
        if sim < cutoff:
            breakpoints.append(i + 1)  # +1 because we split AFTER this index
    
    return breakpoints


def semantic_chunk_messages(
    messages: list[dict],
    method: str = "percentile",
    threshold: float = 90,
    min_chunk_size: int = 2,
    max_chunk_size: int = 30,
) -> list[SemanticChunk]:
    """
    Split messages into semantically coherent chunks.
    
    Args:
        messages: List of message dicts with 'content' key
        method: Breakpoint detection method
        threshold: Threshold value (90 = split at bottom 10%)
        min_chunk_size: Minimum messages per chunk
        max_chunk_size: Maximum messages per chunk (force split)
        
    Returns:
        List of SemanticChunk objects
    """
    if len(messages) < 2:
        return [SemanticChunk(
            messages=messages,
            start_index=0,
            end_index=len(messages),
            avg_similarity=1.0,
        )]
    
    # Extract content for embedding
    contents = [m.get("content", "") for m in messages]
    
    # Filter out empty content
    valid_indices = [i for i, c in enumerate(contents) if c and len(c.strip()) > 5]
    if len(valid_indices) < 2:
        return [SemanticChunk(
            messages=messages,
            start_index=0,
            end_index=len(messages),
            avg_similarity=1.0,
        )]
    
    # Generate embeddings using local model
    from apps.api.src.core.llm_factory import get_embedding_model
    
    embedding_model = get_embedding_model()
    valid_contents = [contents[i] for i in valid_indices]
    
    try:
        embeddings = embedding_model.embed_documents(valid_contents)
    except Exception as e:
        # Fallback: return single chunk
        return [SemanticChunk(
            messages=messages,
            start_index=0,
            end_index=len(messages),
            avg_similarity=1.0,
        )]
    
    # Calculate consecutive similarities
    similarities = calculate_similarities(embeddings)
    
    if not similarities:
        return [SemanticChunk(
            messages=messages,
            start_index=0,
            end_index=len(messages),
            avg_similarity=1.0,
        )]
    
    # Find breakpoints
    breakpoints = find_breakpoints(similarities, method, threshold)
    
    # Map breakpoints back to original message indices
    original_breakpoints = []
    for bp in breakpoints:
        if bp < len(valid_indices):
            original_breakpoints.append(valid_indices[bp])
    
    # Build chunks
    chunks = []
    start_idx = 0
    
    for bp in original_breakpoints:
        if bp - start_idx >= min_chunk_size:
            chunk_msgs = messages[start_idx:bp]
            chunks.append(SemanticChunk(
                messages=chunk_msgs,
                start_index=start_idx,
                end_index=bp,
                avg_similarity=0.8,  # Approximate
            ))
            start_idx = bp
    
    # Add final chunk
    if start_idx < len(messages):
        remaining = messages[start_idx:]
        if len(remaining) >= min_chunk_size or not chunks:
            chunks.append(SemanticChunk(
                messages=remaining,
                start_index=start_idx,
                end_index=len(messages),
                avg_similarity=0.8,
            ))
        elif chunks:
            # Merge small final chunk with previous
            chunks[-1] = SemanticChunk(
                messages=chunks[-1].messages + remaining,
                start_index=chunks[-1].start_index,
                end_index=len(messages),
                avg_similarity=chunks[-1].avg_similarity,
            )
    
    # Enforce max chunk size
    final_chunks = []
    for chunk in chunks:
        if len(chunk.messages) <= max_chunk_size:
            final_chunks.append(chunk)
        else:
            # Split oversized chunks evenly
            n_splits = (len(chunk.messages) + max_chunk_size - 1) // max_chunk_size
            split_size = len(chunk.messages) // n_splits
            
            for i in range(0, len(chunk.messages), split_size):
                sub_messages = chunk.messages[i:i + split_size]
                if len(sub_messages) >= min_chunk_size:
                    final_chunks.append(SemanticChunk(
                        messages=sub_messages,
                        start_index=chunk.start_index + i,
                        end_index=chunk.start_index + i + len(sub_messages),
                        avg_similarity=chunk.avg_similarity,
                    ))
    
    return final_chunks if final_chunks else [SemanticChunk(
        messages=messages,
        start_index=0,
        end_index=len(messages),
        avg_similarity=1.0,
    )]
