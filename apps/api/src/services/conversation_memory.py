"""
Conversation Memory - Stores recent messages for session context.

Provides short-term memory for ongoing conversations so the bot
can reference what was just discussed.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class ConversationMessage:
    """A single message in conversation history."""
    role: str  # "user" or "assistant"
    content: str
    author_name: str
    timestamp: datetime


@dataclass
class ConversationSession:
    """A conversation session with recent messages."""
    messages: list[ConversationMessage] = field(default_factory=list)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    
    def add_message(self, role: str, content: str, author_name: str):
        """Add a message to the session."""
        self.messages.append(ConversationMessage(
            role=role,
            content=content,
            author_name=author_name,
            timestamp=datetime.utcnow(),
        ))
        self.last_activity = datetime.utcnow()
        
        # Keep only last 20 messages to avoid context overflow
        if len(self.messages) > 20:
            self.messages = self.messages[-20:]
    
    def get_context(self, max_messages: int = 10) -> str:
        """Get formatted conversation context."""
        if not self.messages:
            return ""
        
        recent = self.messages[-max_messages:]
        lines = []
        for msg in recent:
            prefix = "User" if msg.role == "user" else "Assistant"
            if msg.author_name and msg.role == "user":
                prefix = msg.author_name
            lines.append(f"{prefix}: {msg.content}")
        
        return "\n".join(lines)
    
    def is_expired(self, timeout_minutes: int = 30) -> bool:
        """Check if session has expired."""
        return datetime.utcnow() - self.last_activity > timedelta(minutes=timeout_minutes)


class ConversationMemory:
    """
    In-memory conversation storage keyed by channel_id.
    
    Each channel maintains its own conversation history.
    Sessions expire after 30 minutes of inactivity.
    """
    
    def __init__(self):
        # Key: channel_id, Value: ConversationSession
        self._sessions: dict[int, ConversationSession] = defaultdict(ConversationSession)
    
    def add_user_message(self, channel_id: int, content: str, author_name: str):
        """Record a user message."""
        self._cleanup_expired()
        self._sessions[channel_id].add_message("user", content, author_name)
    
    def add_assistant_message(self, channel_id: int, content: str):
        """Record an assistant (bot) response."""
        self._cleanup_expired()
        self._sessions[channel_id].add_message("assistant", content, "Assistant")
    
    def get_context(self, channel_id: int, max_messages: int = 10) -> str:
        """Get conversation context for a channel."""
        if channel_id not in self._sessions:
            return ""
        
        session = self._sessions[channel_id]
        if session.is_expired():
            del self._sessions[channel_id]
            return ""
        
        return session.get_context(max_messages)
    
    def clear_channel(self, channel_id: int):
        """Clear conversation history for a channel."""
        if channel_id in self._sessions:
            del self._sessions[channel_id]
    
    def _cleanup_expired(self):
        """Remove expired sessions."""
        expired = [
            cid for cid, session in self._sessions.items()
            if session.is_expired()
        ]
        for cid in expired:
            del self._sessions[cid]


# Global instance
conversation_memory = ConversationMemory()


def get_recent_channel_messages(
    guild_id: int,
    channel_id: int,
    limit: int = 30,
) -> list[dict]:
    """
    Fetch the last N messages from a channel from PostgreSQL.
    
    This provides short-term memory without needing RAG/Qdrant.
    Messages are returned in chronological order (oldest first).
    
    Args:
        guild_id: Guild ID for multi-tenant filtering
        channel_id: Channel ID to fetch messages from
        limit: Maximum number of messages (default 30)
        
    Returns:
        List of message dicts with author_name, content, timestamp
    """
    from sqlalchemy import create_engine, text
    from apps.api.src.core.config import get_settings
    
    settings = get_settings()
    sync_url = settings.database_url.replace("+asyncpg", "")
    engine = create_engine(sync_url, pool_pre_ping=True)
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT m.content, m.message_timestamp, 
                   u.username, u.global_name
            FROM messages m
            JOIN users u ON m.author_id = u.id
            WHERE m.guild_id = :guild_id
              AND m.channel_id = :channel_id
              AND m.is_deleted = FALSE
              AND m.content IS NOT NULL
              AND LENGTH(m.content) > 0
            ORDER BY m.message_timestamp DESC
            LIMIT :limit
        """), {
            "guild_id": guild_id,
            "channel_id": channel_id,
            "limit": limit,
        })
        
        rows = result.fetchall()
    
    # Reverse to get chronological order (oldest first)
    messages = []
    for row in reversed(rows):
        messages.append({
            "author_name": row.global_name or row.username,
            "content": row.content,
            "timestamp": row.message_timestamp,
        })
    
    return messages


def format_recent_messages_as_context(messages: list[dict]) -> str:
    """
    Format recent messages as text context for LLM.
    
    Args:
        messages: List of message dicts from get_recent_channel_messages
        
    Returns:
        Formatted string of recent messages
    """
    if not messages:
        return ""
    
    lines = []
    for msg in messages:
        timestamp = msg["timestamp"]
        time_str = timestamp.strftime("%H:%M") if timestamp else ""
        lines.append(f"[{time_str}] {msg['author_name']}: {msg['content']}")
    
    return "\n".join(lines)


def search_recent_messages(
    messages: list[dict],
    query: str,
    case_sensitive: bool = False,
) -> list[dict]:
    """
    Simple text search through recent messages.
    
    For queries about recent activity, this avoids the need for vector search.
    
    Args:
        messages: List of message dicts
        query: Search query
        case_sensitive: Whether to match case
        
    Returns:
        Matching messages
    """
    if not case_sensitive:
        query = query.lower()
    
    matches = []
    for msg in messages:
        content = msg["content"] if case_sensitive else msg["content"].lower()
        if query in content:
            matches.append(msg)
    
    return matches
