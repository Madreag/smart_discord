#!/usr/bin/env python3
"""
Index existing PostgreSQL messages to Qdrant vector database.

Usage:
    python scripts/index_to_qdrant.py --guild-id YOUR_GUILD_ID
"""

import sys
from pathlib import Path
from uuid import uuid4
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text


def get_db_engine():
    """Get database engine."""
    sync_url = "postgresql://postgres:postgres@localhost:5432/smart_discord"
    return create_engine(sync_url, pool_pre_ping=True)


def index_messages(guild_id: int):
    """Index all messages for a guild to Qdrant."""
    from apps.api.src.core.llm_factory import get_embedding_model
    from apps.api.src.services.qdrant_service import qdrant_service
    from apps.api.src.services.enrichment_service import enrich_session
    
    print(f"Initializing Qdrant collection...")
    qdrant_service.ensure_collection()
    
    print(f"Loading embedding model...")
    embedding_model = get_embedding_model()
    
    engine = get_db_engine()
    
    # Fetch all messages grouped by channel
    print(f"\nFetching messages for guild {guild_id}...")
    
    with engine.connect() as conn:
        # Get channels with messages
        channels = conn.execute(text("""
            SELECT DISTINCT c.id, c.name 
            FROM channels c
            JOIN messages m ON m.channel_id = c.id
            WHERE m.guild_id = :guild_id AND m.is_deleted = FALSE
        """), {"guild_id": guild_id}).fetchall()
        
        total_indexed = 0
        
        for channel in channels:
            channel_id, channel_name = channel.id, channel.name
            print(f"\nProcessing #{channel_name}...")
            
            # Fetch messages for this channel (including bot messages for recall)
            messages = conn.execute(text("""
                SELECT m.id, m.content, m.message_timestamp, m.author_id,
                       u.username, u.global_name
                FROM messages m
                JOIN users u ON m.author_id = u.id
                WHERE m.guild_id = :guild_id 
                  AND m.channel_id = :channel_id
                  AND m.is_deleted = FALSE
                  AND m.content IS NOT NULL
                  AND m.content != ''
                ORDER BY m.message_timestamp ASC
            """), {"guild_id": guild_id, "channel_id": channel_id}).fetchall()
            
            if not messages:
                print(f"  No messages found")
                continue
            
            # Convert to Message objects for hybrid sessionizer
            from apps.bot.src.sessionizer import Message
            from apps.bot.src.hybrid_sessionizer import hybrid_sessionize
            
            message_objs = [
                Message(
                    id=msg.id,
                    channel_id=channel_id,
                    author_id=msg.author_id,
                    content=msg.content,
                    timestamp=msg.message_timestamp,
                    reply_to_id=None,
                )
                for msg in messages
            ]
            
            # Build username lookup
            username_map = {msg.author_id: msg.global_name or msg.username for msg in messages}
            
            # Use hybrid sessionizer (time + semantic)
            print(f"  Applying hybrid sessionization ({len(messages)} messages)...")
            sessions = hybrid_sessionize(
                message_objs,
                semantic_split_threshold=15,
                min_session_size=2,
                max_session_size=30,
            )
            print(f"  Created {len(sessions)} sessions")
            
            for session in sessions:
                # Enrich messages
                enriched_messages = [
                    {
                        "content": m.content,
                        "author_name": username_map.get(m.author_id, f"User#{m.author_id}"),
                        "timestamp": m.timestamp,
                    }
                    for m in session.messages
                ]
                
                enriched_text = enrich_session(enriched_messages, channel_name=channel_name)
                
                # Generate embedding
                embedding = embedding_model.embed_query(enriched_text)
                
                # Upsert to Qdrant
                session_id = str(uuid4())
                message_ids = session.message_ids
                author_ids = list(session.author_ids)
                
                success = qdrant_service.upsert_session(
                    session_id=session_id,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    embedding=embedding,
                    message_ids=message_ids,
                    content_preview=enriched_text[:500],
                    start_time=session.start_time.isoformat() if session.start_time else "",
                    end_time=session.end_time.isoformat() if session.end_time else "",
                    author_ids=author_ids,
                )
                
                if success:
                    total_indexed += len(session.messages)
                else:
                    print(f"  Failed to index session")
        
        print(f"\n{'='*50}")
        print(f"Indexing complete! Total messages indexed: {total_indexed}")
        
        # Show collection info
        info = qdrant_service.get_collection_info()
        print(f"Qdrant collection: {info['name']}")
        print(f"Total vectors: {info['vectors_count']}")
        print(f"{'='*50}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Index messages to Qdrant")
    parser.add_argument("--guild-id", type=int, required=True, help="Discord Guild ID")
    args = parser.parse_args()
    
    index_messages(args.guild_id)
