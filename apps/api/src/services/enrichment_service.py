"""
Metadata Enrichment - Prepends context to text before embedding.

Format: "[Author @ timestamp]: content"

This helps embeddings capture WHO said WHAT and WHEN.
"""

import re
from datetime import datetime
from typing import Optional

from sqlalchemy import create_engine, text

# Cache for user lookups
_user_cache: dict[int, str] = {}
_engine = None


def _get_engine():
    """Get database engine for user lookups."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            "postgresql://postgres:postgres@localhost:5432/smart_discord",
            pool_pre_ping=True,
        )
    return _engine


def resolve_user_mention(user_id: int) -> str:
    """Resolve a Discord user ID to their display name."""
    if user_id in _user_cache:
        return _user_cache[user_id]
    
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT global_name, username FROM users WHERE id = :user_id
            """), {"user_id": user_id})
            row = result.fetchone()
            if row:
                name = row.global_name or row.username
                _user_cache[user_id] = name
                return name
    except Exception:
        pass
    
    return f"User#{user_id}"


def clean_discord_mentions(content: str) -> str:
    """
    Replace Discord mention IDs with actual usernames.
    
    Patterns:
    - <@123456789> -> @Username
    - <@!123456789> -> @Username (nickname mention)
    - <@&123456789> -> @role (role mentions)
    """
    def replace_user_mention(match):
        user_id = int(match.group(1))
        username = resolve_user_mention(user_id)
        return f"@{username}"
    
    # Replace user mentions: <@123456789> or <@!123456789>
    content = re.sub(r'<@!?(\d+)>', replace_user_mention, content)
    
    # Replace role mentions with @role placeholder
    content = re.sub(r'<@&(\d+)>', '@role', content)
    
    # Replace channel mentions with #channel placeholder
    content = re.sub(r'<#(\d+)>', '#channel', content)
    
    return content


def enrich_message(
    content: str,
    author_name: str,
    timestamp: datetime,
    channel_name: Optional[str] = None,
) -> str:
    """
    Enrich a single message with metadata.
    
    Args:
        content: Original message content
        author_name: Display name of author
        timestamp: When message was sent
        channel_name: Optional channel context
        
    Returns:
        Enriched text for embedding
    """
    # Clean Discord mentions to readable usernames
    content = clean_discord_mentions(content)
    
    time_str = timestamp.strftime("%Y-%m-%d %H:%M")
    
    if channel_name:
        return f"[{author_name} in #{channel_name} @ {time_str}]: {content}"
    
    return f"[{author_name} @ {time_str}]: {content}"


def enrich_session(
    messages: list[dict],
    channel_name: Optional[str] = None,
) -> str:
    """
    Enrich a session of messages.
    
    Args:
        messages: List of dicts with 'content', 'author_name', 'timestamp'
        channel_name: Channel context
        
    Returns:
        Concatenated enriched text
    """
    lines = []
    
    for msg in messages:
        enriched = enrich_message(
            content=msg["content"],
            author_name=msg["author_name"],
            timestamp=msg["timestamp"],
            channel_name=None,  # Don't repeat channel on each line
        )
        lines.append(enriched)
    
    if channel_name and len(messages) > 1:
        header = f"Conversation in #{channel_name}:\n"
        return header + "\n".join(lines)
    
    return "\n".join(lines)
