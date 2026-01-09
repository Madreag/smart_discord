-- Discord Community Intelligence System
-- Initial Schema Migration
-- Enforces: Hybrid Storage Integrity Rule (Postgres = Source of Truth)

-- =============================================================================
-- GUILDS TABLE (Discord Servers)
-- =============================================================================
CREATE TABLE IF NOT EXISTS guilds (
    id BIGINT PRIMARY KEY,                          -- Discord snowflake ID
    name VARCHAR(100) NOT NULL,
    icon_hash VARCHAR(64),
    owner_id BIGINT NOT NULL,
    
    -- Configuration
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    premium_tier SMALLINT NOT NULL DEFAULT 0,
    
    -- Timestamps
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_guilds_owner ON guilds(owner_id);
CREATE INDEX idx_guilds_active ON guilds(is_active) WHERE is_active = TRUE;

-- =============================================================================
-- CHANNELS TABLE (with is_indexed flag for Control Plane)
-- =============================================================================
CREATE TABLE IF NOT EXISTS channels (
    id BIGINT PRIMARY KEY,                          -- Discord snowflake ID
    guild_id BIGINT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    type SMALLINT NOT NULL DEFAULT 0,               -- 0=text, 2=voice, etc.
    
    -- Control Plane Flag: determines if messages are indexed to Qdrant
    is_indexed BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Soft delete for "Right to be Forgotten"
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_channels_guild ON channels(guild_id);
CREATE INDEX idx_channels_indexed ON channels(guild_id, is_indexed) WHERE is_indexed = TRUE;

-- =============================================================================
-- MESSAGES TABLE (Source of Truth for all Discord messages)
-- =============================================================================
CREATE TABLE IF NOT EXISTS messages (
    id BIGINT PRIMARY KEY,                          -- Discord snowflake ID
    channel_id BIGINT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    guild_id BIGINT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
    author_id BIGINT NOT NULL,
    
    -- Content
    content TEXT NOT NULL,
    
    -- Threading/Reply context for Sliding Window Sessionizer
    reply_to_id BIGINT REFERENCES messages(id) ON DELETE SET NULL,
    thread_id BIGINT,
    
    -- Metadata
    attachment_count SMALLINT NOT NULL DEFAULT 0,
    embed_count SMALLINT NOT NULL DEFAULT 0,
    mention_count SMALLINT NOT NULL DEFAULT 0,
    
    -- Vector sync status (for Hybrid Storage integrity)
    qdrant_point_id UUID,                           -- NULL if not yet indexed
    indexed_at TIMESTAMPTZ,
    
    -- Soft delete for "Right to be Forgotten"
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    
    -- Timestamps (message_timestamp = Discord's created_at)
    message_timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Primary query patterns
CREATE INDEX idx_messages_channel_time ON messages(channel_id, message_timestamp DESC);
CREATE INDEX idx_messages_guild_time ON messages(guild_id, message_timestamp DESC);
CREATE INDEX idx_messages_author ON messages(author_id, message_timestamp DESC);

-- For Sliding Window Sessionizer: find messages in time windows
CREATE INDEX idx_messages_session ON messages(channel_id, message_timestamp)
    WHERE is_deleted = FALSE;

-- For reply chain analysis
CREATE INDEX idx_messages_reply ON messages(reply_to_id) WHERE reply_to_id IS NOT NULL;

-- For vector sync: find unindexed messages in indexed channels
CREATE INDEX idx_messages_pending_index ON messages(guild_id, channel_id)
    WHERE qdrant_point_id IS NULL AND is_deleted = FALSE;

-- For "Right to be Forgotten": find soft-deleted messages needing Qdrant cleanup
CREATE INDEX idx_messages_deleted ON messages(guild_id, is_deleted) 
    WHERE is_deleted = TRUE AND qdrant_point_id IS NOT NULL;

-- =============================================================================
-- MESSAGE SESSIONS (Sliding Window Sessionizer output)
-- Groups of messages chunked by topic/time for vector embedding
-- =============================================================================
CREATE TABLE IF NOT EXISTS message_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    guild_id BIGINT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
    channel_id BIGINT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    
    -- Session boundaries
    start_message_id BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    end_message_id BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    message_count INT NOT NULL,
    
    -- Time window
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    
    -- Vector storage reference
    qdrant_point_id UUID,
    
    -- Computed summary (for GraphRAG community detection)
    summary TEXT,
    topic_tags TEXT[],
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sessions_guild ON message_sessions(guild_id);
CREATE INDEX idx_sessions_channel_time ON message_sessions(channel_id, start_time DESC);

-- =============================================================================
-- USERS TABLE (Cached Discord user data for analytics)
-- =============================================================================
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,                          -- Discord snowflake ID
    username VARCHAR(32) NOT NULL,
    discriminator VARCHAR(4),                       -- Legacy, may be NULL
    global_name VARCHAR(32),
    avatar_hash VARCHAR(64),
    
    -- Timestamps
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- GUILD_MEMBERS (User-Guild relationship for multi-tenant queries)
-- =============================================================================
CREATE TABLE IF NOT EXISTS guild_members (
    guild_id BIGINT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    nickname VARCHAR(32),
    joined_at TIMESTAMPTZ,
    
    -- Analytics cache
    message_count INT NOT NULL DEFAULT 0,
    last_message_at TIMESTAMPTZ,
    
    PRIMARY KEY (guild_id, user_id)
);

CREATE INDEX idx_members_user ON guild_members(user_id);
CREATE INDEX idx_members_activity ON guild_members(guild_id, message_count DESC);

-- =============================================================================
-- UPDATED_AT TRIGGER FUNCTION
-- =============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply triggers
CREATE TRIGGER update_guilds_updated_at BEFORE UPDATE ON guilds
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_channels_updated_at BEFORE UPDATE ON channels
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_messages_updated_at BEFORE UPDATE ON messages
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
