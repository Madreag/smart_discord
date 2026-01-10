"""
SQLAlchemy ORM Models for Discord Community Intelligence System.

Source of Truth: All message data lives here before Qdrant indexing.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    ARRAY,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class Guild(Base):
    """Discord Guild (Server) configuration."""
    
    __tablename__ = "guilds"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    icon_hash: Mapped[Optional[str]] = mapped_column(String(64))
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    premium_tier: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    
    # Pre-prompt for injecting personality/rules into all bot responses
    pre_prompt: Mapped[Optional[str]] = mapped_column(Text)
    
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    
    # Relationships
    channels: Mapped[list["Channel"]] = relationship(back_populates="guild", cascade="all, delete-orphan")
    messages: Mapped[list["Message"]] = relationship(back_populates="guild", cascade="all, delete-orphan")
    members: Mapped[list["GuildMember"]] = relationship(back_populates="guild", cascade="all, delete-orphan")


class Channel(Base):
    """Discord Channel with is_indexed flag for Control Plane."""
    
    __tablename__ = "channels"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    
    # Control Plane flag
    is_indexed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    
    # Relationships
    guild: Mapped["Guild"] = relationship(back_populates="channels")
    messages: Mapped[list["Message"]] = relationship(back_populates="channel", cascade="all, delete-orphan")


class Message(Base):
    """Discord Message - Source of Truth before Qdrant indexing."""
    
    __tablename__ = "messages"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("channels.id", ondelete="CASCADE"), nullable=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    author_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Threading context for Sliding Window Sessionizer
    reply_to_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("messages.id", ondelete="SET NULL"))
    thread_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    
    # Metadata
    attachment_count: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    embed_count: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    mention_count: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    
    # Vector sync status (Hybrid Storage integrity)
    qdrant_point_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True))
    indexed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Soft delete for "Right to be Forgotten"
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Timestamps
    message_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    
    # Relationships
    guild: Mapped["Guild"] = relationship(back_populates="messages")
    channel: Mapped["Channel"] = relationship(back_populates="messages")
    reply_to: Mapped[Optional["Message"]] = relationship(remote_side=[id])


class MessageSession(Base):
    """Sliding Window Sessionizer output - grouped message chunks."""
    
    __tablename__ = "message_sessions"
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("channels.id", ondelete="CASCADE"), nullable=False)
    
    start_message_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    end_message_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    
    qdrant_point_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True))
    
    summary: Mapped[Optional[str]] = mapped_column(Text)
    topic_tags: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class User(Base):
    """Cached Discord user data for analytics."""
    
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(32), nullable=False)
    discriminator: Mapped[Optional[str]] = mapped_column(String(4))
    global_name: Mapped[Optional[str]] = mapped_column(String(32))
    avatar_hash: Mapped[Optional[str]] = mapped_column(String(64))
    
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    
    # Relationships
    memberships: Mapped[list["GuildMember"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class GuildMember(Base):
    """User-Guild relationship for multi-tenant queries."""
    
    __tablename__ = "guild_members"
    
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    nickname: Mapped[Optional[str]] = mapped_column(String(32))
    joined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Analytics cache
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Relationships
    guild: Mapped["Guild"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="memberships")


class Attachment(Base):
    """Discord file attachments with extracted content for multimodal ingestion."""
    
    __tablename__ = "attachments"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("channels.id", ondelete="CASCADE"), nullable=False)
    
    # File metadata (extracted from Discord, NOT downloaded by bot)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    proxy_url: Mapped[Optional[str]] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Extracted content (populated by API worker)
    description: Mapped[Optional[str]] = mapped_column(Text)
    extracted_text: Mapped[Optional[str]] = mapped_column(Text)
    
    # Processing status
    source_type: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    processing_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    processing_error: Mapped[Optional[str]] = mapped_column(Text)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Vector sync status
    qdrant_point_ids: Mapped[Optional[list[UUID]]] = mapped_column(ARRAY(PGUUID(as_uuid=True)))
    indexed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Soft delete for "Right to be Forgotten"
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    
    # Relationships
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="attachment", cascade="all, delete-orphan")


class DocumentChunk(Base):
    """Recursive/Semantic chunking output for document processing."""
    
    __tablename__ = "document_chunks"
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    attachment_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("attachments.id", ondelete="CASCADE"), nullable=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    
    # Chunk metadata
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(32), default="text", nullable=False)
    
    # Hierarchy
    parent_chunk_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_chunks.id", ondelete="SET NULL"))
    heading_context: Mapped[Optional[str]] = mapped_column(Text)
    
    # Vector reference
    qdrant_point_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True))
    indexed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    
    # Relationships
    attachment: Mapped["Attachment"] = relationship(back_populates="chunks")
    parent: Mapped[Optional["DocumentChunk"]] = relationship(remote_side=[id])
