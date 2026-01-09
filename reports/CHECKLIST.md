# Discord Community Intelligence System - Implementation Checklist

> **Purpose**: Track implementation progress for all missing features  
> **Source**: REPORT1.md through REPORT12.md

---

## P0 - Critical Priority

### RBAC Permission Check (REPORT1)
- [ ] Create `apps/web/src/types/discord.ts` with permission types
- [ ] Create `apps/web/src/lib/permissions.ts` with bitfield utilities
- [ ] Update `apps/web/src/app/dashboard/page.tsx` with guild filtering
- [ ] Update `apps/web/src/app/dashboard/[guildId]/page.tsx` with server-side validation
- [ ] Add unit tests for permission utilities
- [ ] Add integration tests for RBAC flow
- [ ] Test with real Discord accounts (admin vs member)

### Qdrant Vector Indexing Pipeline (REPORT2)
- [ ] Add dependencies: `qdrant-client`, `fastembed`
- [ ] Create `apps/api/src/services/embedding_service.py`
- [ ] Create `apps/api/src/services/qdrant_service.py`
- [ ] Create `apps/api/src/services/enrichment_service.py`
- [ ] Update `apps/bot/src/tasks.py` with real implementation
- [ ] Update `apps/api/src/agents/vector_rag.py` to use new services
- [ ] Add Qdrant collection initialization on API startup
- [ ] Test with real Discord messages
- [ ] Run batch indexing for existing messages

### on_message_edit Handler (REPORT3)
- [ ] Add `on_raw_message_delete` handler
- [ ] Add `on_raw_bulk_message_delete` handler
- [ ] Add `on_raw_message_edit` handler
- [ ] Add `reindex_message` Celery task
- [ ] Update `delete_message_vectors` task with real Qdrant deletion
- [ ] Add unit tests for event handlers
- [ ] Add integration tests for full pipeline
- [ ] Add logging for debugging
- [ ] Test with real Discord messages

---

## P1 - High Priority

### Real Analytics Data in Dashboard (REPORT11)
- [ ] Add `/guilds/{guild_id}/stats` endpoint to API
- [ ] Add `/guilds/{guild_id}/stats/timeseries` endpoint
- [ ] Add `/guilds/{guild_id}/stats/top-channels` endpoint
- [ ] Create TypeScript types in `apps/web/src/types/stats.ts`
- [ ] Create API client in `apps/web/src/lib/api.ts`
- [ ] Create `StatsCard` component
- [ ] Create `IndexingProgress` component
- [ ] Create `ActivityChart` component
- [ ] Update `apps/web/src/app/dashboard/[guildId]/page.tsx`
- [ ] Add Redis caching for stats
- [ ] Test with real guild data

### Metadata Enrichment Before Embedding (REPORT2)
- [ ] Implement `enrich_message()` function
- [ ] Implement `enrich_session()` function
- [ ] Integrate enrichment into indexing pipeline
- [ ] Test enriched embeddings improve query results

### Complete "Right to be Forgotten" (REPORT3)
- [ ] Wire `on_message_delete` to Qdrant deletion
- [ ] Implement `delete_message_vectors` Celery task
- [ ] Verify Postgres soft delete works
- [ ] Verify Qdrant hard delete works
- [ ] Test full deletion flow

---

## P2 - Medium Priority

### GraphRAG for Thematic Analysis (REPORT4)
- [ ] Choose implementation approach (LlamaIndex vs Custom vs Lightweight)
- [ ] Add dependencies to `pyproject.toml`
- [ ] Create `apps/api/src/services/graphrag_service.py`
- [ ] Add `GRAPH_RAG` to `RouterIntent` enum
- [ ] Add GraphRAG patterns to router
- [ ] Create `apps/api/src/agents/graphrag.py`
- [ ] Add `build_guild_graph` Celery task
- [ ] Add `/ai buildgraph` slash command
- [ ] Test with real server data
- [ ] Set up periodic graph rebuilding

### Semantic Chunking (REPORT5)
- [ ] Add numpy dependency (if not present)
- [ ] Create `apps/api/src/services/semantic_chunker.py`
- [ ] Create `apps/bot/src/hybrid_sessionizer.py`
- [ ] Update indexing pipeline to use hybrid approach
- [ ] Add configuration for semantic threshold
- [ ] Test with high-activity channel data
- [ ] Benchmark embedding costs

### PII Scrubbing (REPORT6)
- [ ] Install dependencies: `presidio-analyzer`, `presidio-anonymizer`, `spacy`
- [ ] Download spaCy model: `python -m spacy download en_core_web_lg`
- [ ] Create `apps/api/src/services/pii_service.py`
- [ ] Add custom Discord recognizer for tokens/webhooks
- [ ] Integrate with message ingestion
- [ ] Add per-guild PII settings to database
- [ ] Add unit tests
- [ ] Test with real Discord messages containing PII

---

## P3 - Lower Priority

### Additional Slash Commands (REPORT12)
- [ ] Create `apps/bot/src/commands/__init__.py` with `AICommands` group
- [ ] Implement `/ai summary` command
- [ ] Implement `/ai search` command
- [ ] Implement `/ai topics` command
- [ ] Add `/summary` API endpoint
- [ ] Add `/search` API endpoint
- [ ] Add `/guilds/{guild_id}/topics` API endpoint
- [ ] Add cooldowns to prevent abuse
- [ ] Register commands in bot setup
- [ ] Sync commands with Discord
- [ ] Test all commands in a real server

### Rate Limit Management (REPORT9)
- [ ] Create `apps/bot/src/rate_limiter.py`
- [ ] Create `apps/bot/src/leaky_bucket.py`
- [ ] Integrate with Discord HTTP requests
- [ ] Add logging for rate limit events
- [ ] Test with bulk message operations
- [ ] Monitor 429 error frequency

### CI/CD Pipeline (REPORT10)
- [ ] Create `.github/workflows/ci.yml`
- [ ] Add Ruff configuration to `pyproject.toml`
- [ ] Add MyPy configuration
- [ ] Configure ESLint for TypeScript
- [ ] Add security scanning (Trivy, Bandit)
- [ ] Set up GitHub Container Registry
- [ ] Configure repository secrets

---

## Partial Implementations (Complete These)

### Hybrid Storage Design (REPORT7)
- [ ] Create `apps/api/src/services/storage_service.py`
- [ ] Add `sync_status` column to `message_sessions` table
- [ ] Implement `mark_indexed` / `mark_session_indexed`
- [ ] Add `verify_sync` Celery task
- [ ] Add `repair_sync` Celery task
- [ ] Set up Celery Beat schedule
- [ ] Add `/sync-health` API endpoint
- [ ] Add sync health to dashboard UI
- [ ] Test failure recovery scenarios

### Celery/Redis Task Queue (REPORT8)
- [ ] Update `apps/bot/src/celery_config.py` with production settings
- [ ] Implement all task logic (remove TODOs)
- [ ] Add retry logic with exponential backoff
- [ ] Set up priority queues (high, default, low)
- [ ] Implement dead letter queue pattern
- [ ] Add Flower to `docker-compose.yml`
- [ ] Add Celery Beat for scheduled tasks
- [ ] Test worker restart scenarios
- [ ] Add monitoring/alerting for queue depth

---

## Security Hardening (REPORT10)

### Prompt Injection Protection
- [ ] Create `apps/api/src/services/security_service.py`
- [ ] Add prompt injection detection
- [ ] Add input sanitization
- [ ] Add output validation
- [ ] Integrate with `/ask` endpoint
- [ ] Add security logging/alerting
- [ ] Test with known injection patterns

---

## Implementation Roadmap

| Week | Focus | Reports |
|------|-------|---------|
| 1 | P0 Critical | REPORT1, REPORT2, REPORT3 |
| 2 | P1 High + Security | REPORT11, REPORT10 (security) |
| 3 | P2 Medium | REPORT4, REPORT5, REPORT6 |
| 4 | P3 + Partial | REPORT7, REPORT8, REPORT9, REPORT12 |

---

## Quick Reference

| Report | Feature | Priority |
|--------|---------|----------|
| REPORT1 | RBAC Permission Check | P0 |
| REPORT2 | Qdrant Vector Indexing + Metadata Enrichment | P0/P1 |
| REPORT3 | Message Edit/Delete Handlers + Right to be Forgotten | P0/P1 |
| REPORT4 | GraphRAG for Thematic Analysis | P2 |
| REPORT5 | Semantic Chunking | P2 |
| REPORT6 | PII Scrubbing | P2 |
| REPORT7 | Hybrid Storage Design (Partial) | — |
| REPORT8 | Celery/Redis Task Queue (Scaffolded) | — |
| REPORT9 | Rate Limit Management | P3 |
| REPORT10 | CI/CD Pipeline + Security | P3 |
| REPORT11 | Real Analytics Dashboard Data | P1 |
| REPORT12 | Additional Slash Commands | P3 |
