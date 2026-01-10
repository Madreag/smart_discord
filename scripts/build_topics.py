#!/usr/bin/env python3
"""
Build Topic Clusters for GraphRAG

Analyzes server messages and builds topic clusters for thematic queries.
Run periodically to keep topics up to date.

Usage:
    python scripts/build_topics.py --guild-id 123456789
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text


def build_topics(guild_id: int, max_messages: int = 5000):
    """Build topic clusters for a guild."""
    from apps.api.src.services.thematic_analyzer import get_thematic_analyzer
    
    print(f"Building topic clusters for guild {guild_id}...")
    
    # Connect to database
    engine = create_engine(
        "postgresql://postgres:postgres@localhost:5432/smart_discord",
        pool_pre_ping=True,
    )
    
    # Fetch messages
    print("Fetching messages from database...")
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT m.content
            FROM messages m
            WHERE m.guild_id = :guild_id
              AND m.is_deleted = FALSE
              AND LENGTH(m.content) > 20
            ORDER BY m.message_timestamp DESC
            LIMIT :limit
        """), {"guild_id": guild_id, "limit": max_messages})
        
        messages = [row.content for row in result.fetchall()]
    
    print(f"Found {len(messages)} messages")
    
    if len(messages) < 20:
        print("Not enough messages for topic analysis (need at least 20)")
        return
    
    # Build clusters
    print("Clustering messages into topics...")
    analyzer = get_thematic_analyzer(guild_id)
    clusters = analyzer.fit(messages)
    
    if not clusters:
        print("Could not build topic clusters")
        return
    
    # Display results
    print(f"\n{'='*60}")
    print(f"Found {len(clusters)} topic clusters:")
    print('='*60)
    
    for i, cluster in enumerate(clusters, 1):
        terms = ", ".join(cluster.top_terms[:5])
        print(f"\n{i}. {terms}")
        print(f"   Messages: {cluster.message_count}")
        if cluster.sample_messages:
            print(f"   Sample: \"{cluster.sample_messages[0][:80]}...\"")
    
    print(f"\n{'='*60}")
    print(f"Topic clusters saved to: {analyzer.cache_file}")
    print("The bot can now answer thematic queries like:")
    print("  - 'What are the main topics people discuss?'")
    print("  - 'What are common complaints?'")
    print("  - 'Overview of server discussions'")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build topic clusters for GraphRAG")
    parser.add_argument("--guild-id", type=int, required=True, help="Discord guild ID")
    parser.add_argument("--max-messages", type=int, default=5000, help="Max messages to analyze")
    
    args = parser.parse_args()
    build_topics(args.guild_id, args.max_messages)
