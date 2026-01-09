-- DM Messages Table for RAG-based Long-term Memory
-- Stores direct message conversations with vector embeddings

-- =============================================================================
-- DM_MESSAGES TABLE (Direct Message conversations)
-- =============================================================================
CREATE TABLE IF NOT EXISTS dm_messages (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,                        -- Discord user ID
    role VARCHAR(20) NOT NULL,                      -- 'user' or 'assistant'
    content TEXT NOT NULL,
    
    -- Vector storage reference
    qdrant_point_id UUID,                           -- NULL if not yet indexed
    indexed_at TIMESTAMPTZ,
    
    -- Timestamps
    message_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Primary query pattern: get recent messages for a user
CREATE INDEX idx_dm_messages_user_time ON dm_messages(user_id, message_timestamp DESC);

-- For vector sync: find unindexed messages
CREATE INDEX idx_dm_messages_pending_index ON dm_messages(user_id)
    WHERE qdrant_point_id IS NULL;
