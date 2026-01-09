# REPORT 4: GraphRAG for Thematic Analysis

> **Priority**: P2 (Medium)  
> **Effort**: 3-5 days  
> **Status**: Not Implemented

---

## 1. Executive Summary

Standard vector RAG excels at "needle in haystack" queries but fails at thematic analysis. When a user asks "What are the main complaints about the server?", vector search returns 5 specific messages instead of synthesizing trends across hundreds.

**GraphRAG** solves this by:
1. Extracting entities and relationships into a knowledge graph
2. Running community detection (Leiden algorithm)
3. Pre-generating summaries for each community
4. Answering broad queries using these high-level summaries

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        INDEXING PIPELINE                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Messages → Entity Extraction → Graph Construction → Communities    │
│                    │                    │                │          │
│                    ▼                    ▼                ▼          │
│             [User, Topic,        [NetworkX         [Leiden         │
│              Channel, ...]        Graph]           Clusters]        │
│                                                         │          │
│                                                         ▼          │
│                                              Community Summaries    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                         QUERY PIPELINE                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Query → Router → "Is this thematic?" → Yes → GraphRAG Agent        │
│                          │                         │                │
│                          No                        ▼                │
│                          │              Retrieve Community          │
│                          ▼              Summaries + Synthesize      │
│                   Standard Vector RAG                               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Implementation Options

### Option A: LlamaIndex PropertyGraphIndex (Recommended)

LlamaIndex provides production-ready GraphRAG with hierarchical Leiden clustering.

**Pros**:
- Battle-tested implementation
- Built-in community detection
- Automatic summary generation
- Integrates with existing LLM setup

**Cons**:
- Additional dependency
- Learning curve

### Option B: Custom NetworkX + LLM Implementation

Build from scratch using NetworkX for graphs and LLM for extraction/summarization.

**Pros**:
- Full control
- No new dependencies
- Simpler for small scale

**Cons**:
- More code to maintain
- Need to implement community detection

### Option C: Microsoft GraphRAG Library

Microsoft's official GraphRAG implementation.

**Pros**:
- Well-documented
- Production-grade

**Cons**:
- Heavier dependency
- Designed for document corpora, not chat

---

## 4. Implementation Guide (Option A: LlamaIndex)

### Dependencies

```bash
pip install llama-index llama-index-graph-stores-neo4j graspologic networkx
```

### Step 1: Graph Store Setup

```python
# apps/api/src/services/graphrag_service.py
"""
GraphRAG Service - Knowledge graph with community detection.

Uses LlamaIndex PropertyGraphIndex with hierarchical Leiden clustering.
"""

from typing import Optional
from dataclasses import dataclass

from llama_index.core import PropertyGraphIndex, Document
from llama_index.core.indices.property_graph import (
    SimpleLLMPathExtractor,
    ImplicitPathExtractor,
)
from llama_index.llms.openai import OpenAI

from apps.api.src.core.config import get_settings


@dataclass
class Community:
    """A cluster of related entities."""
    id: int
    entities: list[str]
    summary: str
    level: int  # Hierarchy level (0 = top)


class GraphRAGService:
    """
    GraphRAG implementation using LlamaIndex.
    
    Maintains a per-guild knowledge graph with community summaries.
    """
    
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.settings = get_settings()
        self.llm = OpenAI(
            model="gpt-4o-mini",
            api_key=self.settings.openai_api_key,
            temperature=0,
        )
        self._index: Optional[PropertyGraphIndex] = None
        self._communities: list[Community] = []
    
    async def build_graph_from_messages(
        self,
        messages: list[dict],
    ) -> PropertyGraphIndex:
        """
        Build knowledge graph from message data.
        
        Args:
            messages: List of dicts with 'content', 'author', 'channel', 'timestamp'
            
        Returns:
            PropertyGraphIndex with extracted entities and relationships
        """
        # Convert messages to Documents
        documents = []
        for msg in messages:
            # Include metadata for context
            text = f"[{msg['author']} in #{msg['channel']}]: {msg['content']}"
            doc = Document(
                text=text,
                metadata={
                    "author": msg["author"],
                    "channel": msg["channel"],
                    "timestamp": msg["timestamp"],
                    "guild_id": self.guild_id,
                },
            )
            documents.append(doc)
        
        # Build graph with entity extraction
        self._index = PropertyGraphIndex.from_documents(
            documents,
            llm=self.llm,
            embed_kg_nodes=True,
            kg_extractors=[
                # Extract entities and relationships using LLM
                SimpleLLMPathExtractor(
                    llm=self.llm,
                    max_paths_per_chunk=10,
                    num_workers=4,
                ),
                # Also extract implicit relationships
                ImplicitPathExtractor(),
            ],
            show_progress=True,
        )
        
        return self._index
    
    async def detect_communities(self) -> list[Community]:
        """
        Run hierarchical Leiden community detection.
        
        Returns list of communities with summaries.
        """
        if not self._index:
            raise ValueError("Graph not built yet. Call build_graph_from_messages first.")
        
        import networkx as nx
        from graspologic.partition import hierarchical_leiden
        
        # Convert to NetworkX graph
        G = nx.Graph()
        
        for node in self._index.property_graph_store.get_all_nodes():
            G.add_node(node.id, label=node.label, **node.properties)
        
        for edge in self._index.property_graph_store.get_all_edges():
            G.add_edge(edge.source_id, edge.target_id, relation=edge.label)
        
        if len(G.nodes) < 3:
            # Too few nodes for community detection
            return []
        
        # Run hierarchical Leiden
        community_map = hierarchical_leiden(G, max_cluster_size=10)
        
        # Group nodes by community
        communities_dict = {}
        for node_id, community_id in community_map.items():
            if community_id not in communities_dict:
                communities_dict[community_id] = []
            communities_dict[community_id].append(node_id)
        
        # Generate summaries for each community
        self._communities = []
        for comm_id, entities in communities_dict.items():
            if len(entities) < 2:
                continue
            
            summary = await self._generate_community_summary(entities)
            self._communities.append(Community(
                id=comm_id,
                entities=entities,
                summary=summary,
                level=0,
            ))
        
        return self._communities
    
    async def _generate_community_summary(self, entities: list[str]) -> str:
        """Generate a natural language summary of a community."""
        # Get node details
        node_details = []
        for entity_id in entities[:10]:  # Limit for prompt size
            node = self._index.property_graph_store.get_node(entity_id)
            if node:
                node_details.append(f"- {node.label}: {node.properties}")
        
        prompt = f"""Summarize the following cluster of related entities from a Discord server discussion:

Entities:
{chr(10).join(node_details)}

Provide a 2-3 sentence summary of what this cluster represents (e.g., a topic, a group of users, a type of discussion).
"""
        
        response = await self.llm.acomplete(prompt)
        return response.text.strip()
    
    async def query_thematic(self, query: str) -> str:
        """
        Answer a thematic/broad query using community summaries.
        
        Args:
            query: Broad question like "What are the main complaints?"
            
        Returns:
            Synthesized answer from community summaries
        """
        if not self._communities:
            return "No community analysis available. The graph needs to be built first."
        
        # Gather all community summaries
        summaries = "\n\n".join([
            f"**Topic Cluster {c.id}**: {c.summary}"
            for c in self._communities
        ])
        
        prompt = f"""Based on these topic clusters identified in the Discord server:

{summaries}

Answer the user's question: {query}

Synthesize information across multiple clusters to give a comprehensive answer. 
If the question can't be answered from the summaries, say so.
"""
        
        response = await self.llm.acomplete(prompt)
        return response.text.strip()


# Per-guild service instances (cached)
_guild_services: dict[int, GraphRAGService] = {}


def get_graphrag_service(guild_id: int) -> GraphRAGService:
    """Get or create GraphRAG service for a guild."""
    if guild_id not in _guild_services:
        _guild_services[guild_id] = GraphRAGService(guild_id)
    return _guild_services[guild_id]
```

### Step 2: Router Integration

```python
# apps/api/src/agents/router.py (add patterns)

GRAPHRAG_PATTERNS: list[re.Pattern[str]] = [
    # Thematic/summary queries
    re.compile(r"\b(main|common|frequent|popular)\b.*\b(complaints?|issues?|topics?|themes?|concerns?)\b", re.I),
    re.compile(r"\b(summarize|overview|trends?)\b.*\b(server|community|discussions?)\b", re.I),
    re.compile(r"\bwhat (do|does) (everyone|people|users?|members?) (think|say|feel)\b", re.I),
    re.compile(r"\b(general|overall) (sentiment|opinion|feeling)\b", re.I),
    # Relationship queries
    re.compile(r"\bwho (talks?|interacts?) (with|to|about)\b", re.I),
    re.compile(r"\b(connections?|relationships?) between\b", re.I),
]

# Add to RouterIntent enum
class RouterIntent(str, Enum):
    ANALYTICS_DB = "analytics_db"
    VECTOR_RAG = "vector_rag"
    GRAPH_RAG = "graph_rag"  # NEW
    WEB_SEARCH = "web_search"
    GENERAL_KNOWLEDGE = "general_knowledge"
```

### Step 3: GraphRAG Agent

```python
# apps/api/src/agents/graphrag.py
"""
GraphRAG Agent - Handles thematic queries using knowledge graph.
"""

from packages.shared.python.models import AskResponse, RouterIntent
from apps.api.src.services.graphrag_service import get_graphrag_service


async def process_graphrag_query(
    query: str,
    guild_id: int,
) -> AskResponse:
    """
    Process a thematic query using GraphRAG.
    
    Args:
        query: Broad/thematic question
        guild_id: Guild ID
        
    Returns:
        AskResponse with synthesized answer
    """
    import time
    start_time = time.time()
    
    service = get_graphrag_service(guild_id)
    
    # Check if graph is built
    if not service._index:
        # Graph not built yet - need to run indexing first
        answer = (
            "The knowledge graph for this server hasn't been built yet. "
            "Please run `/ai buildgraph` first, or ask a more specific question "
            "that can be answered with regular search."
        )
    else:
        # Query using community summaries
        answer = await service.query_thematic(query)
    
    execution_time = (time.time() - start_time) * 1000
    
    return AskResponse(
        answer=answer,
        sources=[],  # GraphRAG doesn't have specific message sources
        routed_to=RouterIntent.GRAPH_RAG,
        execution_time_ms=execution_time,
    )
```

### Step 4: Background Graph Building Task

```python
# apps/bot/src/tasks.py

@celery_app.task(
    bind=True,
    name="build_guild_graph",
    time_limit=3600,  # 1 hour max
)
def build_guild_graph(self, guild_id: int, max_messages: int = 10000) -> dict:
    """
    Build knowledge graph for a guild (background task).
    
    This is expensive - should be run periodically, not on every query.
    """
    import asyncio
    from apps.api.src.services.graphrag_service import get_graphrag_service
    
    engine = get_db_engine()
    
    # Fetch recent messages
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT m.content, u.username as author, c.name as channel, m.message_timestamp
            FROM messages m
            JOIN users u ON m.author_id = u.id
            JOIN channels c ON m.channel_id = c.id
            WHERE m.guild_id = :guild_id
              AND m.is_deleted = FALSE
              AND LENGTH(m.content) > 10
            ORDER BY m.message_timestamp DESC
            LIMIT :limit
        """), {"guild_id": guild_id, "limit": max_messages})
        
        messages = [
            {
                "content": row.content,
                "author": row.author,
                "channel": row.channel,
                "timestamp": row.message_timestamp.isoformat(),
            }
            for row in result.fetchall()
        ]
    
    if not messages:
        return {"status": "skipped", "reason": "no_messages"}
    
    # Build graph
    service = get_graphrag_service(guild_id)
    
    asyncio.run(service.build_graph_from_messages(messages))
    communities = asyncio.run(service.detect_communities())
    
    return {
        "status": "success",
        "guild_id": guild_id,
        "messages_processed": len(messages),
        "communities_found": len(communities),
    }
```

---

## 5. Lightweight Alternative (No LlamaIndex)

For simpler deployments, use TF-IDF + KMeans clustering:

```python
# apps/api/src/services/lightweight_graphrag.py
"""
Lightweight thematic analysis using TF-IDF + KMeans.

No external graph dependencies required.
"""

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from collections import defaultdict


class LightweightThematicAnalyzer:
    """Simple topic clustering without full GraphRAG."""
    
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.vectorizer = TfidfVectorizer(
            max_features=1000,
            stop_words="english",
            ngram_range=(1, 2),
        )
        self.clusters: dict[int, list[str]] = {}
        self.cluster_summaries: dict[int, str] = {}
    
    def fit(self, messages: list[str], n_clusters: int = 10):
        """Cluster messages into topics."""
        if len(messages) < n_clusters:
            n_clusters = max(2, len(messages) // 2)
        
        # Vectorize
        tfidf_matrix = self.vectorizer.fit_transform(messages)
        
        # Cluster
        kmeans = KMeans(n_clusters=n_clusters, random_state=42)
        labels = kmeans.fit_predict(tfidf_matrix)
        
        # Group messages by cluster
        self.clusters = defaultdict(list)
        for msg, label in zip(messages, labels):
            self.clusters[label].append(msg)
        
        # Get top terms per cluster
        feature_names = self.vectorizer.get_feature_names_out()
        for i, center in enumerate(kmeans.cluster_centers_):
            top_indices = center.argsort()[-5:][::-1]
            top_terms = [feature_names[idx] for idx in top_indices]
            self.cluster_summaries[i] = f"Topics: {', '.join(top_terms)}"
    
    async def answer_query(self, query: str, llm) -> str:
        """Answer thematic query using cluster summaries."""
        summaries = "\n".join([
            f"Cluster {i}: {summary} ({len(msgs)} messages)"
            for i, (summary, msgs) in enumerate(
                zip(self.cluster_summaries.values(), self.clusters.values())
            )
        ])
        
        prompt = f"""Based on these topic clusters from the server:

{summaries}

Answer: {query}"""
        
        response = await llm.acomplete(prompt)
        return response.text
```

---

## 6. Performance Considerations

| Approach | Build Time | Query Time | Memory |
|----------|------------|------------|--------|
| LlamaIndex GraphRAG | 5-30 min | 2-5 sec | High |
| Custom NetworkX | 2-10 min | 1-3 sec | Medium |
| Lightweight TF-IDF | 10-60 sec | <1 sec | Low |

**Recommendations**:
- Small servers (<10k messages): Lightweight TF-IDF
- Medium servers (10k-100k): Custom NetworkX
- Large servers (>100k): LlamaIndex with incremental updates

---

## 7. References

- [LlamaIndex GraphRAG Cookbook](https://docs.llamaindex.ai/en/stable/examples/cookbooks/GraphRAG_v1/)
- [Microsoft GraphRAG](https://github.com/microsoft/graphrag)
- [Graspologic Hierarchical Leiden](https://graspologic.readthedocs.io/)
- [Neo4j GraphRAG Integration](https://neo4j.com/blog/developer/microsoft-graphrag-neo4j/)

---

## 8. Checklist

- [ ] Choose implementation approach (LlamaIndex vs Custom vs Lightweight)
- [ ] Add dependencies to `pyproject.toml`
- [ ] Create `apps/api/src/services/graphrag_service.py`
- [ ] Add `GRAPH_RAG` to `RouterIntent` enum
- [ ] Add GraphRAG patterns to router
- [ ] Create `apps/api/src/agents/graphrag.py`
- [ ] Add `build_guild_graph` Celery task
- [ ] Add `/ai buildgraph` slash command
- [ ] Test with real server data
- [ ] Set up periodic graph rebuilding
