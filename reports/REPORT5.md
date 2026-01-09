# REPORT 5: Semantic Chunking for Chat Data

> **Priority**: P2 (Medium)  
> **Effort**: 1-2 days  
> **Status**: Not Implemented (only time-based exists)

---

## 1. Executive Summary

The current sessionizer groups messages by **time gaps only** (15-minute threshold). This fails for high-activity channels where conversations flow continuously but topics shift frequently.

**Semantic Chunking** detects topic boundaries by measuring embedding similarity between consecutive messages, splitting where similarity drops sharply.

---

## 2. Current vs Target

| Aspect | Current (Time-based) | Target (Semantic) |
|--------|---------------------|-------------------|
| Split Logic | 15-min gap | Similarity drop |
| Topic Aware | No | Yes |
| Cost | Free | Embedding cost |
| Accuracy | Low for busy channels | High |

---

## 3. Algorithm Deep Dive

### The Semantic Chunking Algorithm

```
1. Segment text into sentences/messages
2. Generate embedding for each segment
3. Calculate cosine similarity between consecutive segments
4. Detect "breakpoints" where similarity drops significantly
5. Split into chunks at breakpoints
```

### Breakpoint Detection Methods

**Method 1: Percentile Threshold (Recommended)**
```python
# Split when similarity is below the Nth percentile
threshold = np.percentile(similarities, 5)  # Bottom 5%
```

**Method 2: Standard Deviation**
```python
# Split when similarity is N standard deviations below mean
threshold = mean_similarity - (3 * std_similarity)
```

**Method 3: Interquartile Range**
```python
# Split at statistical outliers
Q1, Q3 = np.percentile(similarities, [25, 75])
IQR = Q3 - Q1
threshold = Q1 - 1.5 * IQR
```

---

## 4. Implementation Guide

### Dependencies

```bash
pip install langchain-experimental langchain-openai numpy
```

### Option A: LangChain SemanticChunker

```python
# apps/api/src/services/semantic_chunker.py
"""
Semantic Chunking using LangChain's SemanticChunker.

Reference: https://www.firecrawl.dev/blog/best-chunking-strategies-rag-2025
"""

from langchain_experimental.text_splitter import SemanticChunker
from langchain_openai import OpenAIEmbeddings

from apps.api.src.core.config import get_settings


def get_semantic_chunker(
    breakpoint_type: str = "percentile",
    threshold_amount: float = 95,
) -> SemanticChunker:
    """
    Create a semantic chunker.
    
    Args:
        breakpoint_type: "percentile", "standard_deviation", or "interquartile"
        threshold_amount: Threshold value (95 for percentile = bottom 5%)
        
    Returns:
        Configured SemanticChunker
    """
    settings = get_settings()
    
    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        openai_api_key=settings.openai_api_key,
    )
    
    return SemanticChunker(
        embeddings=embeddings,
        breakpoint_threshold_type=breakpoint_type,
        breakpoint_threshold_amount=threshold_amount,
    )


def semantic_chunk_text(text: str) -> list[str]:
    """
    Split text into semantically coherent chunks.
    
    Args:
        text: Concatenated messages
        
    Returns:
        List of chunk strings
    """
    chunker = get_semantic_chunker()
    chunks = chunker.split_text(text)
    return chunks
```

### Option B: Custom Implementation (No LangChain)

```python
# apps/api/src/services/semantic_chunker.py
"""
Custom Semantic Chunking - No external dependencies except embeddings.
"""

import numpy as np
from typing import Optional
from dataclasses import dataclass

from apps.api.src.services.embedding_service import generate_embeddings_batch


@dataclass
class SemanticChunk:
    """A semantically coherent group of messages."""
    messages: list[dict]
    start_index: int
    end_index: int
    avg_similarity: float


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Calculate cosine similarity between two vectors."""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def calculate_similarities(embeddings: list[list[float]]) -> list[float]:
    """
    Calculate cosine similarity between consecutive embeddings.
    
    Returns list of N-1 similarity scores for N embeddings.
    """
    embeddings_np = [np.array(e) for e in embeddings]
    
    similarities = []
    for i in range(len(embeddings_np) - 1):
        sim = cosine_similarity(embeddings_np[i], embeddings_np[i + 1])
        similarities.append(sim)
    
    return similarities


def find_breakpoints(
    similarities: list[float],
    method: str = "percentile",
    threshold: float = 95,
) -> list[int]:
    """
    Find indices where semantic breakpoints occur.
    
    Args:
        similarities: List of similarity scores
        method: "percentile", "std_dev", or "iqr"
        threshold: Threshold value (meaning depends on method)
        
    Returns:
        List of breakpoint indices
    """
    if not similarities:
        return []
    
    similarities_np = np.array(similarities)
    
    if method == "percentile":
        # Split when similarity is in the bottom (100-threshold)%
        cutoff = np.percentile(similarities_np, 100 - threshold)
    elif method == "std_dev":
        # Split when similarity is threshold std devs below mean
        mean = np.mean(similarities_np)
        std = np.std(similarities_np)
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
    threshold: float = 95,
    min_chunk_size: int = 2,
    max_chunk_size: int = 50,
) -> list[SemanticChunk]:
    """
    Split messages into semantically coherent chunks.
    
    Args:
        messages: List of message dicts with 'content' key
        method: Breakpoint detection method
        threshold: Threshold value
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
    
    # Generate embeddings
    embeddings = generate_embeddings_batch(contents)
    
    # Calculate consecutive similarities
    similarities = calculate_similarities(embeddings)
    
    # Find breakpoints
    breakpoints = find_breakpoints(similarities, method, threshold)
    
    # Build chunks
    chunks = []
    start_idx = 0
    
    for bp in breakpoints:
        if bp - start_idx >= min_chunk_size:
            chunk_sims = similarities[start_idx:bp-1] if bp > start_idx + 1 else [1.0]
            chunks.append(SemanticChunk(
                messages=messages[start_idx:bp],
                start_index=start_idx,
                end_index=bp,
                avg_similarity=float(np.mean(chunk_sims)) if chunk_sims else 1.0,
            ))
            start_idx = bp
    
    # Add final chunk
    if start_idx < len(messages):
        chunk_sims = similarities[start_idx:] if start_idx < len(similarities) else [1.0]
        chunks.append(SemanticChunk(
            messages=messages[start_idx:],
            start_index=start_idx,
            end_index=len(messages),
            avg_similarity=float(np.mean(chunk_sims)) if chunk_sims else 1.0,
        ))
    
    # Enforce max chunk size
    final_chunks = []
    for chunk in chunks:
        if len(chunk.messages) <= max_chunk_size:
            final_chunks.append(chunk)
        else:
            # Split oversized chunks
            for i in range(0, len(chunk.messages), max_chunk_size):
                sub_messages = chunk.messages[i:i + max_chunk_size]
                if len(sub_messages) >= min_chunk_size:
                    final_chunks.append(SemanticChunk(
                        messages=sub_messages,
                        start_index=chunk.start_index + i,
                        end_index=chunk.start_index + i + len(sub_messages),
                        avg_similarity=chunk.avg_similarity,
                    ))
    
    return final_chunks
```

### Hybrid Approach: Time + Semantic

```python
# apps/bot/src/hybrid_sessionizer.py
"""
Hybrid Sessionizer - Time-based first, then semantic refinement.

Strategy:
1. First pass: Split by time gaps (existing sessionizer)
2. Second pass: For large sessions, apply semantic splitting
"""

from apps.bot.src.sessionizer import sessionize_messages, Message
from apps.api.src.services.semantic_chunker import semantic_chunk_messages, SemanticChunk


def hybrid_sessionize(
    messages: list[Message],
    time_gap_minutes: int = 15,
    semantic_threshold: float = 95,
    semantic_split_threshold: int = 20,  # Apply semantic if > N messages
) -> list[SemanticChunk]:
    """
    Hybrid approach: time-based first, then semantic.
    
    Args:
        messages: List of Message objects
        time_gap_minutes: Time gap threshold for first pass
        semantic_threshold: Percentile threshold for semantic splitting
        semantic_split_threshold: Min session size to apply semantic splitting
        
    Returns:
        List of SemanticChunk objects
    """
    # First pass: time-based sessionization
    time_sessions = sessionize_messages(messages)
    
    final_chunks = []
    
    for session in time_sessions:
        if len(session.messages) <= semantic_split_threshold:
            # Small session - keep as is
            final_chunks.append(SemanticChunk(
                messages=[{
                    "id": m.id,
                    "content": m.content,
                    "author_id": m.author_id,
                    "timestamp": m.timestamp,
                } for m in session.messages],
                start_index=0,
                end_index=len(session.messages),
                avg_similarity=1.0,
            ))
        else:
            # Large session - apply semantic splitting
            msg_dicts = [{
                "id": m.id,
                "content": m.content,
                "author_id": m.author_id,
                "timestamp": m.timestamp,
            } for m in session.messages]
            
            semantic_chunks = semantic_chunk_messages(
                msg_dicts,
                method="percentile",
                threshold=semantic_threshold,
            )
            final_chunks.extend(semantic_chunks)
    
    return final_chunks
```

---

## 5. Cost Analysis

### Embedding Costs (OpenAI)

| Model | Price per 1M tokens | Dims |
|-------|---------------------|------|
| text-embedding-3-small | $0.02 | 1536 |
| text-embedding-3-large | $0.13 | 3072 |

**Example**: 10,000 messages × 50 tokens avg = 500K tokens = **$0.01**

### Local Alternative (FastEmbed)

Using FastEmbed with `all-MiniLM-L6-v2`:
- **Cost**: Free (runs locally)
- **Speed**: ~50ms per message on CPU
- **Quality**: Slightly lower than OpenAI

---

## 6. When to Use Semantic Chunking

| Scenario | Recommendation |
|----------|----------------|
| Low-activity channel | Time-based only |
| High-activity, single topic | Time-based only |
| High-activity, topic shifts | **Semantic chunking** |
| Mixed activity | **Hybrid approach** |

---

## 7. References

- [Firecrawl: Best Chunking Strategies 2025](https://www.firecrawl.dev/blog/best-chunking-strategies-rag-2025)
- [LangChain SemanticChunker](https://python.langchain.com/docs/modules/data_connection/document_transformers/semantic-chunker)
- [Multimodal.dev: Semantic Chunking for RAG](https://www.multimodal.dev/post/semantic-chunking-for-rag)

---

## 8. Checklist

- [ ] Add numpy dependency (if not present)
- [ ] Create `apps/api/src/services/semantic_chunker.py`
- [ ] Create `apps/bot/src/hybrid_sessionizer.py`
- [ ] Update indexing pipeline to use hybrid approach
- [ ] Add configuration for semantic threshold
- [ ] Test with high-activity channel data
- [ ] Benchmark embedding costs
