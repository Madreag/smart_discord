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
