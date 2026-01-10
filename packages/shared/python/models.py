"""
Shared Pydantic models for Discord Community Intelligence System.
These mirror the TypeScript interfaces in src/types.ts.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# =============================================================================
# Core Discord Entities
# =============================================================================

class Guild(BaseModel):
    """Discord Guild (Server) configuration."""
    id: int = Field(..., description="Discord snowflake ID")
    name: str
    icon_hash: Optional[str] = None
    owner_id: int
    is_active: bool = True
    premium_tier: int = 0
    joined_at: datetime
    created_at: datetime
    updated_at: datetime


class ChannelType(int, Enum):
    TEXT = 0
    DM = 1
    VOICE = 2
    GROUP_DM = 3
    CATEGORY = 4
    NEWS = 5
    FORUM = 15


class Channel(BaseModel):
    """Discord Channel with is_indexed flag for Control Plane."""
    id: int
    guild_id: int
    name: str
    type: ChannelType = ChannelType.TEXT
    is_indexed: bool = False  # Control Plane flag
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class Message(BaseModel):
    """Discord Message - Source of Truth."""
    id: int
    channel_id: int
    guild_id: int
    author_id: int
    content: str
    reply_to_id: Optional[int] = None
    thread_id: Optional[int] = None
    attachment_count: int = 0
    embed_count: int = 0
    mention_count: int = 0
    qdrant_point_id: Optional[str] = None
    indexed_at: Optional[datetime] = None
    is_deleted: bool = False
    deleted_at: Optional[datetime] = None
    message_timestamp: datetime
    created_at: datetime
    updated_at: datetime


class User(BaseModel):
    """Cached Discord user data."""
    id: int
    username: str
    discriminator: Optional[str] = None
    global_name: Optional[str] = None
    avatar_hash: Optional[str] = None
    first_seen_at: datetime
    updated_at: datetime


class GuildMember(BaseModel):
    """User-Guild relationship."""
    guild_id: int
    user_id: int
    nickname: Optional[str] = None
    joined_at: Optional[datetime] = None
    message_count: int = 0
    last_message_at: Optional[datetime] = None


# =============================================================================
# API Request/Response Types
# =============================================================================

class RouterIntent(str, Enum):
    """Intent classification for the Router Agent."""
    ANALYTICS_DB = "analytics_db"
    VECTOR_RAG = "vector_rag"
    GRAPH_RAG = "graph_rag"  # Thematic/broad queries
    WEB_SEARCH = "web_search"
    GENERAL_KNOWLEDGE = "general_knowledge"


class AskQuery(BaseModel):
    """Request payload for /ask endpoint."""
    guild_id: int
    query: str
    channel_ids: Optional[list[int]] = None
    channel_id: Optional[int] = None  # Current channel for conversation memory
    author_name: Optional[str] = None  # For conversation context


class MessageSource(BaseModel):
    """Source reference in RAG responses."""
    message_id: int
    channel_id: int
    author_id: int
    content: str
    timestamp: datetime
    relevance_score: float


class AskResponse(BaseModel):
    """Response payload from /ask endpoint."""
    answer: str
    sources: list[MessageSource]
    routed_to: RouterIntent
    execution_time_ms: float


# =============================================================================
# Control Plane Types
# =============================================================================

class ChannelIndexConfig(BaseModel):
    """Channel indexing configuration for dashboard."""
    channel_id: int
    channel_name: str
    is_indexed: bool
    message_count: int
    last_indexed_at: Optional[datetime] = None


class TopContributor(BaseModel):
    """Top contributor stats."""
    user_id: int
    username: str
    message_count: int


class GuildStats(BaseModel):
    """Guild analytics summary."""
    total_messages: int
    indexed_messages: int
    active_users: int
    top_contributors: list[TopContributor]


class GuildDashboard(BaseModel):
    """Full guild dashboard data."""
    guild: Guild
    channels: list[ChannelIndexConfig]
    stats: GuildStats


# =============================================================================
# Celery Task Types
# =============================================================================

class IndexTaskPayload(BaseModel):
    """Payload for vector indexing task."""
    guild_id: int
    channel_id: int
    message_ids: list[int]


class DeleteTaskPayload(BaseModel):
    """Payload for message deletion task (Right to be Forgotten)."""
    guild_id: int
    message_id: int
    qdrant_point_id: str
