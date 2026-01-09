"""
Sliding Window Sessionizer

Groups messages into sessions based on:
1. Same channel_id
2. Time difference < 15 minutes
3. Topic shifts (detected via reply chain breaks)

CONSTRAINT: Do NOT chunk by token count alone.
"""

from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional


# Session break threshold
SESSION_GAP_MINUTES = 15


@dataclass
class Message:
    """Lightweight message representation for sessionization."""
    id: int
    channel_id: int
    author_id: int
    content: str
    timestamp: datetime
    reply_to_id: Optional[int] = None


@dataclass
class Session:
    """A group of related messages."""
    channel_id: int
    messages: list[Message] = field(default_factory=list)
    
    @property
    def start_time(self) -> Optional[datetime]:
        if not self.messages:
            return None
        return self.messages[0].timestamp
    
    @property
    def end_time(self) -> Optional[datetime]:
        if not self.messages:
            return None
        return self.messages[-1].timestamp
    
    @property
    def message_ids(self) -> list[int]:
        return [m.id for m in self.messages]
    
    @property
    def author_ids(self) -> set[int]:
        return {m.author_id for m in self.messages}
    
    def add_message(self, message: Message) -> None:
        """Add a message to the session."""
        self.messages.append(message)
    
    def get_text(self) -> str:
        """Get concatenated session text."""
        return "\n".join(m.content for m in self.messages)


def should_break_session(
    current: Message,
    previous: Message,
    active_reply_chains: set[int],
) -> bool:
    """
    Determine if a new session should start.
    
    Break conditions:
    1. Time gap > 15 minutes
    2. Reply chain break (message replies to something outside current session)
    
    Args:
        current: Current message being processed
        previous: Previous message in the stream
        active_reply_chains: Set of message IDs in active reply chains
        
    Returns:
        True if session should break, False otherwise
    """
    # Rule 1: Time gap exceeds threshold
    time_diff = current.timestamp - previous.timestamp
    if time_diff > timedelta(minutes=SESSION_GAP_MINUTES):
        return True
    
    # Rule 2: Reply chain break
    # If this message is a reply to something not in the active session
    if current.reply_to_id is not None:
        if current.reply_to_id not in active_reply_chains:
            # Replying to something outside the session = topic shift
            return True
    
    return False


def sessionize_messages(messages: list[Message]) -> list[Session]:
    """
    Group messages into sessions using the Sliding Window algorithm.
    
    Args:
        messages: List of messages sorted by timestamp ascending
        
    Returns:
        List of Session objects
    """
    if not messages:
        return []
    
    # Sort by timestamp to ensure correct ordering
    sorted_messages = sorted(messages, key=lambda m: m.timestamp)
    
    sessions: list[Session] = []
    current_session = Session(channel_id=sorted_messages[0].channel_id)
    active_reply_chains: set[int] = set()
    
    for i, message in enumerate(sorted_messages):
        # First message always starts a session
        if i == 0:
            current_session.add_message(message)
            active_reply_chains.add(message.id)
            continue
        
        previous = sorted_messages[i - 1]
        
        # Check for channel change (always break)
        if message.channel_id != current_session.channel_id:
            if current_session.messages:
                sessions.append(current_session)
            current_session = Session(channel_id=message.channel_id)
            active_reply_chains = set()
        
        # Check for session break
        elif should_break_session(message, previous, active_reply_chains):
            if current_session.messages:
                sessions.append(current_session)
            current_session = Session(channel_id=message.channel_id)
            active_reply_chains = set()
        
        # Add message to current session
        current_session.add_message(message)
        active_reply_chains.add(message.id)
        
        # Track reply chain
        if message.reply_to_id:
            active_reply_chains.add(message.reply_to_id)
    
    # Don't forget the last session
    if current_session.messages:
        sessions.append(current_session)
    
    return sessions


def process_channel_messages(
    messages: list[Message],
    min_session_messages: int = 3,
    max_session_messages: int = 50,
) -> list[Session]:
    """
    Process messages from a channel into sessions with size constraints.
    
    Args:
        messages: List of messages from a single channel
        min_session_messages: Minimum messages per session (filter small sessions)
        max_session_messages: Maximum messages before forcing a break
        
    Returns:
        List of valid sessions
    """
    # First pass: basic sessionization
    sessions = sessionize_messages(messages)
    
    # Second pass: split oversized sessions
    final_sessions: list[Session] = []
    
    for session in sessions:
        if len(session.messages) <= max_session_messages:
            if len(session.messages) >= min_session_messages:
                final_sessions.append(session)
        else:
            # Split into chunks of max_session_messages
            for i in range(0, len(session.messages), max_session_messages):
                chunk = session.messages[i:i + max_session_messages]
                if len(chunk) >= min_session_messages:
                    new_session = Session(channel_id=session.channel_id)
                    new_session.messages = chunk
                    final_sessions.append(new_session)
    
    return final_sessions
