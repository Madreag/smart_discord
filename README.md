# Discord Community Intelligence System

A distributed, event-driven microservices architecture for intelligent Discord community analytics with **multi-LLM provider support** (OpenAI, Anthropic, xAI).

## Quick Start

### Prerequisites

- **Node.js** 18+ and **pnpm** (`npm install -g pnpm`)
- **Python** 3.11+
- **Docker** (optional, for infrastructure services)

### Step 1: Clone and Install Dependencies

```bash
# Install Node.js dependencies
pnpm install

# Create Python virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e packages/shared -e packages/database -e apps/api -e apps/bot
```

### Step 2: Configure Environment

```bash
# Copy the example environment file
cp .env.example .env

# Generate AUTH_SECRET and add to .env
openssl rand -base64 32
```

Edit `.env` with your API keys (see [LLM Provider Configuration](#llm-provider-configuration)).

### Step 3: Start Infrastructure (Docker)

```bash
docker-compose up -d postgres qdrant redis
```

### Step 4: Run the Services

```bash
# Terminal 1: FastAPI API (port 8000)
source .venv/bin/activate
uvicorn apps.api.src.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Next.js Dashboard (port 3000)
pnpm dev:web

# Terminal 3: Discord Bot (optional)
source .venv/bin/activate
python -m apps.bot.src.bot
```

### Step 5: Verify Installation

```bash
curl http://localhost:8000/health
# → {"status":"healthy","version":"0.1.0"}
```

Open http://localhost:3000 for the dashboard.

---

## LLM Provider Configuration

Choose your provider by setting `LLM_PROVIDER` in `.env`:

| Provider | Model | API Key Variable |
|----------|-------|------------------|
| **OpenAI** | gpt-4o-mini | `OPENAI_API_KEY` |
| **Anthropic** | claude-sonnet-4-20250514 | `ANTHROPIC_API_KEY` |
| **xAI** | grok-beta | `XAI_API_KEY` |

```env
# Example: Using Anthropic
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Embeddings: 'local' (free) or 'openai'
EMBEDDING_PROVIDER=local
```

**Local embeddings** use `sentence-transformers` - no API key required.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CONTROL PLANE                                   │
│                    (Next.js 15 + Auth.js Dashboard)                         │
│                         apps/web - Port 3000                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            COGNITIVE LAYER                                   │
│                      (FastAPI + LangGraph Agents)                           │
│                         apps/api - Port 8000                                │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                     │
│  │   Router    │───▶│ Analytics   │───▶│  Vector     │    ┌──────────────┐ │
│  │   Agent     │    │ (Text-SQL)  │    │  RAG        │───▶│ Web Search   │ │
│  └─────────────┘    └─────────────┘    └─────────────┘    └──────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                        ┌─────────────┴─────────────┐
                        ▼                           ▼
┌───────────────────────────────┐   ┌───────────────────────────────┐
│         PostgreSQL            │   │          Qdrant               │
│      (Source of Truth)        │   │     (Semantic Index)          │
│  • guilds, channels, messages │   │  • guild_id payload filtering │
│  • is_indexed flags           │   │  • message embeddings         │
│  • soft delete tracking       │   │  • session summaries          │
└───────────────────────────────┘   └───────────────────────────────┘
                        ▲
                        │
┌─────────────────────────────────────────────────────────────────────────────┐
│                           INGESTION LAYER                                    │
│                    (discord.py + Celery Workers)                            │
│                              apps/bot                                        │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐         │
│  │ Gateway Listener │───▶│  Redis/Celery   │───▶│  Index Worker   │         │
│  │ (Event Loop)     │    │  Task Queue     │    │  (Embedding)    │         │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘         │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Monorepo Structure

```
smart_discord/
├── apps/
│   ├── web/          # Next.js 15 Control Plane Dashboard
│   ├── api/          # FastAPI + LangGraph Cognitive Layer
│   └── bot/          # discord.py Ingestion Worker
├── packages/
│   ├── shared/       # Shared Types (Pydantic/TS Interfaces)
│   └── database/     # SQL Migrations + Qdrant Schema
├── package.json      # Workspace root
├── pnpm-workspace.yaml
└── turbo.json
```

## Core Constraints & Invariants

### Hybrid Storage Integrity Rule
- **Cannot write to Qdrant** without a corresponding record in PostgreSQL
- **Soft Delete + Hard Delete**: `on_message_delete` sets `is_deleted=True` in Postgres AND hard deletes the vector in Qdrant
- **All Qdrant payloads** must include `guild_id` for strict multi-tenant filtering

### Sliding Window Sessionizer
Messages are NOT chunked by token count alone. Instead:
1. Group messages if `channel_id` matches AND `time_difference < 15 minutes`
2. Break chunks on **Topic Shifts** or **Reply Chain breaks**

### Deferral Pattern
Upon receiving `/ai ask`, the bot MUST immediately call:
```python
await interaction.response.defer(thinking=True)
```
This prevents the 3-second Discord timeout while LangGraph processes.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/ask` | POST | Process natural language query |
| `/classify` | POST | Classify query intent |
| `/settings/provider` | GET | Get current LLM config |

## Running Tests

```bash
source .venv/bin/activate
python3 tests/repro_routing.py        # Router Agent (12 tests)
python3 tests/test_sql_validator.py   # SQL Security (19 tests)
python3 tests/test_sessionizer.py     # Sessionizer (8 tests)
```

## Environment Variables Reference

```env
# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smart_discord

# Vector Store
QDRANT_URL=http://localhost:6333

# Task Queue
REDIS_URL=redis://localhost:6379

# Discord
DISCORD_TOKEN=your-bot-token
DISCORD_CLIENT_ID=your-client-id
DISCORD_CLIENT_SECRET=your-client-secret

# LLM Provider (choose one: openai, anthropic, xai)
LLM_PROVIDER=openai
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
XAI_API_KEY=

# Embeddings (local = free, no API key)
EMBEDDING_PROVIDER=local

# Auth (generate: openssl rand -base64 32)
AUTH_SECRET=

# Optional
TAVILY_API_KEY=
```

## License

MIT
