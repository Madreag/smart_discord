"""
Thematic Analyzer - Topic clustering for GraphRAG-style queries.

Uses TF-IDF + KMeans for lightweight thematic analysis.
Answers broad questions like "What are the main topics people discuss?"
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from collections import defaultdict


@dataclass
class TopicCluster:
    """A cluster of related messages."""
    id: int
    top_terms: list[str]
    message_count: int
    sample_messages: list[str] = field(default_factory=list)
    summary: Optional[str] = None


class ThematicAnalyzer:
    """
    Lightweight thematic analysis using TF-IDF + KMeans.
    
    Persists clusters to disk for fast retrieval.
    """
    
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.vectorizer = TfidfVectorizer(
            max_features=500,
            stop_words="english",
            ngram_range=(1, 2),
            min_df=2,
            max_df=0.8,
        )
        self.clusters: list[TopicCluster] = []
        self.built_at: Optional[datetime] = None
        self._cache_dir = Path("/tmp/thematic_cache")
        self._cache_dir.mkdir(exist_ok=True)
    
    @property
    def cache_file(self) -> Path:
        return self._cache_dir / f"guild_{self.guild_id}_topics.json"
    
    def fit(self, messages: list[str], n_clusters: int = 8) -> list[TopicCluster]:
        """
        Cluster messages into topics.
        
        Args:
            messages: List of message content strings
            n_clusters: Number of topic clusters
            
        Returns:
            List of TopicCluster objects
        """
        if len(messages) < 10:
            return []
        
        # Adjust cluster count based on message volume
        n_clusters = min(n_clusters, max(3, len(messages) // 10))
        
        # Filter empty/short messages
        valid_messages = [m for m in messages if len(m.strip()) > 20]
        if len(valid_messages) < n_clusters * 2:
            return []
        
        # Vectorize
        try:
            tfidf_matrix = self.vectorizer.fit_transform(valid_messages)
        except ValueError:
            return []
        
        # Cluster
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = kmeans.fit_predict(tfidf_matrix)
        
        # Group messages by cluster
        cluster_messages: dict[int, list[str]] = defaultdict(list)
        for msg, label in zip(valid_messages, labels):
            cluster_messages[label].append(msg)
        
        # Get top terms per cluster
        feature_names = self.vectorizer.get_feature_names_out()
        self.clusters = []
        
        for i, center in enumerate(kmeans.cluster_centers_):
            top_indices = center.argsort()[-6:][::-1]
            top_terms = [feature_names[idx] for idx in top_indices]
            
            msgs = cluster_messages[i]
            cluster = TopicCluster(
                id=i,
                top_terms=top_terms,
                message_count=len(msgs),
                sample_messages=msgs[:3],  # Keep 3 samples
            )
            self.clusters.append(cluster)
        
        # Sort by message count (most active topics first)
        self.clusters.sort(key=lambda c: c.message_count, reverse=True)
        self.built_at = datetime.utcnow()
        
        # Save to cache
        self._save_cache()
        
        return self.clusters
    
    def _save_cache(self):
        """Save clusters to disk."""
        data = {
            "guild_id": self.guild_id,
            "built_at": self.built_at.isoformat() if self.built_at else None,
            "clusters": [
                {
                    "id": c.id,
                    "top_terms": c.top_terms,
                    "message_count": c.message_count,
                    "sample_messages": c.sample_messages,
                    "summary": c.summary,
                }
                for c in self.clusters
            ],
        }
        self.cache_file.write_text(json.dumps(data, indent=2))
    
    def _load_cache(self) -> bool:
        """Load clusters from disk. Returns True if loaded."""
        if not self.cache_file.exists():
            return False
        
        try:
            data = json.loads(self.cache_file.read_text())
            self.built_at = datetime.fromisoformat(data["built_at"]) if data.get("built_at") else None
            self.clusters = [
                TopicCluster(
                    id=c["id"],
                    top_terms=c["top_terms"],
                    message_count=c["message_count"],
                    sample_messages=c.get("sample_messages", []),
                    summary=c.get("summary"),
                )
                for c in data.get("clusters", [])
            ]
            return len(self.clusters) > 0
        except Exception:
            return False
    
    def get_topics_summary(self) -> str:
        """Get a formatted summary of all topics."""
        if not self.clusters:
            if not self._load_cache():
                return ""
        
        lines = []
        for i, cluster in enumerate(self.clusters, 1):
            terms = ", ".join(cluster.top_terms[:4])
            lines.append(f"{i}. **{terms}** ({cluster.message_count} messages)")
        
        return "\n".join(lines)
    
    async def answer_thematic_query(self, query: str) -> str:
        """
        Answer a thematic query using topic clusters.
        
        Args:
            query: Broad question like "What are the main topics?"
            
        Returns:
            Answer synthesized from topic clusters
        """
        if not self.clusters:
            if not self._load_cache():
                return (
                    "Topic analysis hasn't been run for this server yet. "
                    "Please ask an admin to run the topic analysis first."
                )
        
        # Build context from clusters
        topics_context = []
        for i, cluster in enumerate(self.clusters[:10], 1):
            terms = ", ".join(cluster.top_terms)
            samples = "\n    ".join(f'"{m[:100]}..."' if len(m) > 100 else f'"{m}"' for m in cluster.sample_messages[:2])
            topics_context.append(
                f"Topic {i} ({cluster.message_count} messages): {terms}\n"
                f"  Examples:\n    {samples}"
            )
        
        context = "\n\n".join(topics_context)
        
        # Use LLM to synthesize answer
        try:
            from apps.api.src.core.llm_factory import get_llm
            
            llm = get_llm(temperature=0.3)
            
            prompt = f"""Based on these topic clusters identified from Discord server conversations:

{context}

Answer the user's question: {query}

Synthesize information across the topic clusters to give a comprehensive answer.
Be specific about which topics are most discussed and provide insights about trends.
If the question can't be answered from the topics, say so."""

            from langchain_core.messages import HumanMessage
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return response.content.strip()
            
        except Exception as e:
            # Fallback: just return the topics summary
            return f"Here are the main topics discussed in this server:\n\n{self.get_topics_summary()}"


# Per-guild analyzer cache
_analyzers: dict[int, ThematicAnalyzer] = {}


def get_thematic_analyzer(guild_id: int) -> ThematicAnalyzer:
    """Get or create thematic analyzer for a guild."""
    if guild_id not in _analyzers:
        _analyzers[guild_id] = ThematicAnalyzer(guild_id)
    return _analyzers[guild_id]
