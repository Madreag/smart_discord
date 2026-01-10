-- Multimodal Ingestion: Attachments Table
-- Supports: Images, PDFs, TXT, MD files
-- Enforces: Multi-tenancy via guild_id, Right to be Forgotten via cascade delete

-- =============================================================================
-- ATTACHMENTS TABLE (Discord file attachments with extracted content)
-- =============================================================================
CREATE TABLE IF NOT EXISTS attachments (
    id BIGINT PRIMARY KEY,                              -- Discord attachment ID
    message_id BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    guild_id BIGINT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
    channel_id BIGINT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    
    -- File metadata (extracted from Discord, NOT downloaded by bot)
    url TEXT NOT NULL,                                  -- CDN URL for download by API worker
    proxy_url TEXT,                                     -- Discord proxy URL
    filename VARCHAR(256) NOT NULL,
    content_type VARCHAR(128),                          -- MIME type (image/png, application/pdf, etc.)
    size_bytes INT NOT NULL,                            -- File size for rate limiting
    
    -- Extracted content (populated by API worker)
    description TEXT,                                   -- Vision LLM description for images
    extracted_text TEXT,                                -- Extracted text from PDF/TXT/MD
    
    -- Processing status
    source_type VARCHAR(32) NOT NULL DEFAULT 'unknown', -- 'image', 'pdf', 'text', 'markdown'
    processing_status VARCHAR(32) NOT NULL DEFAULT 'pending', -- 'pending', 'processing', 'completed', 'failed'
    processing_error TEXT,                              -- Error message if failed
    processed_at TIMESTAMPTZ,
    
    -- Vector sync status (for Hybrid Storage integrity)
    qdrant_point_ids UUID[],                            -- Multiple chunks per document
    indexed_at TIMESTAMPTZ,
    chunk_count INT DEFAULT 0,                          -- Number of chunks created
    
    -- Soft delete for "Right to be Forgotten"
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- INDEXES
-- =============================================================================

-- Primary query: find attachments by message
CREATE INDEX idx_attachments_message ON attachments(message_id);

-- Multi-tenant queries: find attachments by guild
CREATE INDEX idx_attachments_guild ON attachments(guild_id);

-- Processing queue: find pending attachments
CREATE INDEX idx_attachments_pending ON attachments(processing_status, created_at)
    WHERE processing_status = 'pending';

-- Vector sync: find unindexed attachments
CREATE INDEX idx_attachments_unindexed ON attachments(guild_id, channel_id)
    WHERE qdrant_point_ids IS NULL AND is_deleted = FALSE AND processing_status = 'completed';

-- Right to be Forgotten: find deleted attachments needing Qdrant cleanup
CREATE INDEX idx_attachments_deleted ON attachments(guild_id, is_deleted)
    WHERE is_deleted = TRUE AND qdrant_point_ids IS NOT NULL;

-- Content type filtering
CREATE INDEX idx_attachments_type ON attachments(guild_id, source_type)
    WHERE is_deleted = FALSE;

-- =============================================================================
-- TRIGGERS
-- =============================================================================

CREATE TRIGGER update_attachments_updated_at BEFORE UPDATE ON attachments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- DOCUMENT CHUNKS TABLE (Recursive/Semantic chunking output)
-- =============================================================================
CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attachment_id BIGINT NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
    guild_id BIGINT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
    
    -- Chunk metadata
    chunk_index INT NOT NULL,                           -- Order within document
    chunk_text TEXT NOT NULL,                           -- The actual chunk content
    chunk_type VARCHAR(32) NOT NULL DEFAULT 'text',     -- 'text', 'header', 'paragraph', 'image_caption'
    
    -- Hierarchy (for semantic chunking)
    parent_chunk_id UUID REFERENCES document_chunks(id) ON DELETE SET NULL,
    heading_context TEXT,                               -- Parent headings for context
    
    -- Vector reference
    qdrant_point_id UUID,
    indexed_at TIMESTAMPTZ,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_chunks_attachment ON document_chunks(attachment_id, chunk_index);
CREATE INDEX idx_chunks_guild ON document_chunks(guild_id);
CREATE INDEX idx_chunks_unindexed ON document_chunks(guild_id)
    WHERE qdrant_point_id IS NULL;
