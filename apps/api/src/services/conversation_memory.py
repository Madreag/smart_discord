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
