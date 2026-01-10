# Implementation Checklist

## P0 - Critical

- [X]**RBAC Permission Check** (REPORT1) — Filter dashboard by admin permissions
- [X]**Qdrant Indexing Pipeline** (REPORT2) — Embedding + upsert services
- [X]**Message Edit/Delete Handlers** (REPORT3) — Sync edits/deletes to Qdrant

## P1 - High

- [X]**Real Dashboard Analytics** (REPORT11) — Replace placeholder stats with real data
- [X]**Metadata Enrichment** (REPORT2) — Add author/channel/time context to embeddings
- [ ]**Right to be Forgotten** (REPORT3) — Complete Qdrant hard-delete on message delete

## P2 - Medium

- [X]**GraphRAG** (REPORT4) — Thematic analysis with knowledge graphs
- [X]**Semantic Chunking** (REPORT5) — Topic-based message grouping
- [ ]**PII Scrubbing** (REPORT6) — Auto-redact emails, phones, tokens

## P3 - Lower

- [X]**Slash Commands** (REPORT12) —`/ai summary`,`/ai search`,`/ai topics`
- [X]**Rate Limiting** (REPORT9) — Pre-emptive Discord rate limit handling
- [X]**CI/CD Pipeline** (REPORT10) — GitHub Actions, linting, security scans

## Infrastructure

- [X]**Hybrid Storage Sync** (REPORT7) — Postgres ↔ Qdrant consistency
- [X]**Celery Tasks** (REPORT8) — Complete TODO implementations, add retries
- [X]**Prompt Injection Protection** (REPORT10) — Input sanitization, output validation

---

## Roadmap

| Week | Focus               |
| ---- | ------------------- |
| 1    | P0 Critical         |
| 2    | P1 High + Security  |
| 3    | P2 Medium           |
| 4    | P3 + Infrastructure |
