# Discord Community Intelligence System

An intelligent Discord bot that answers questions about your server using AI. Supports **multi-LLM providers** (OpenAI, Anthropic, xAI) and can answer both general knowledge questions and server-specific analytics.

## Features

- **AI-Powered Q&A** - Ask questions in Discord using `/ai`
- **Server Analytics** - "Who talks the most?", "How many messages last week?"
- **General Knowledge** - "How many states are in the US?", "What is the capital of France?"
- **Multi-LLM Support** - OpenAI, Anthropic (Claude), or xAI (Grok)
- **Web Dashboard** - Manage channel indexing settings

---

## Quick Start

### Prerequisites

- **Node.js** 18+ and **pnpm** (`npm install -g pnpm`)
- **Python** 3.11+
- **PostgreSQL** (can be installed locally, no Docker required)

### Step 1: Clone and Install Dependencies

```bash
# Install Node.js dependencies
pnpm install

# Create Python virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -e packages/shared -e packages/database -e apps/api -e apps/bot
pip install psycopg2-binary
```

### Step 2: Set Up PostgreSQL

**Option A: Install locally (WSL/Linux)**
```bash
sudo apt update && sudo apt install -y postgresql postgresql-contrib
sudo service postgresql start
sudo -u postgres psql -c "CREATE DATABASE smart_discord;"
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'postgres';"
sudo -u postgres psql -d smart_discord -f packages/database/migrations/001_initial_schema.sql
```

**Option B: Use Docker**
```bash
docker-compose up -d postgres
```

### Step 3: Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# Required: Discord Bot
DISCORD_TOKEN=your-bot-token
DISCORD_CLIENT_ID=your-client-id

# Required: Choose ONE LLM provider
LLM_PROVIDER=anthropic  # or: openai, xai
ANTHROPIC_API_KEY=sk-ant-...  # Anthropic keys start with sk-ant-
# OPENAI_API_KEY=sk-...
# XAI_API_KEY=xai-...

# Database (default works for local PostgreSQL)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smart_discord
```

### Step 4: Set Up Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications/)
2. Create a new application → Bot → Copy the token
3. Enable **Privileged Gateway Intents**:
   - ✅ SERVER MEMBERS INTENT
   - ✅ MESSAGE CONTENT INTENT
4. Invite bot to your server with `applications.commands` and `bot` scopes

### Step 5: Run the Services

```bash
# Terminal 1: API Server
source .venv/bin/activate
uvicorn apps.api.src.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Discord Bot
source .venv/bin/activate
python -m apps.bot.src.bot

# Terminal 3: Dashboard (optional)
pnpm dev:web
```

### Step 6: Verify Installation

```bash
curl http://localhost:8000/health
# → {"status":"healthy","version":"0.1.0"}
```

Bot should show: `Logged in as YourBot#1234`

---

## Using the Bot

### Discord Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/ai question:` | Ask any question | `/ai question: How many states are in the US?` |
| `/stats` | Show server statistics | `/stats` |
| `/index channel:` | Toggle channel indexing (Admin) | `/index channel: #general` |

### Query Types

The bot automatically routes your question to the right handler:

| Type | Examples | What it does |
|------|----------|--------------|
| **General Knowledge** | "What is Python?", "Who wrote Hamlet?" | Direct LLM answer |
| **Server Analytics** | "Who talks the most?", "Messages last week?" | SQL query on your server data |
| **Semantic Search** | "What did people say about the bug?" | Vector search on messages |
| **Web Search** | "Latest Python version?" | Web search (requires Tavily API) |

### Backfilling Historical Messages

New messages are indexed automatically. To import historical messages:

```bash
source .venv/bin/activate
python scripts/backfill_messages.py --guild-id YOUR_GUILD_ID --limit 500
```

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
| `/guilds/{id}/channels` | GET | List guild channels |
| `/guilds/{id}/channels/{id}/index` | PATCH | Toggle channel indexing |

## Troubleshooting

### Bot won't start: "PrivilegedIntentsRequired"
Enable intents in Discord Developer Portal → Bot → Privileged Gateway Intents

### "invalid x-api-key" error
Check your API key format:
- **Anthropic**: starts with `sk-ant-`
- **OpenAI**: starts with `sk-`
- **xAI**: starts with `xai-`

### "No results found" for analytics queries
Run the backfill script to import historical messages:
```bash
python scripts/backfill_messages.py --guild-id YOUR_GUILD_ID --limit 500
```

### PostgreSQL not running (after WSL restart)
```bash
sudo service postgresql start
```

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

# Discord (Required)
DISCORD_TOKEN=your-bot-token
DISCORD_CLIENT_ID=your-client-id

# LLM Provider - choose one (Required)
LLM_PROVIDER=anthropic
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
XAI_API_KEY=xai-...

# Optional services
QDRANT_URL=http://localhost:6333
REDIS_URL=redis://localhost:6379
TAVILY_API_KEY=tvly-...

# Dashboard Auth (generate: openssl rand -base64 32)
AUTH_SECRET=
DISCORD_CLIENT_SECRET=your-client-secret
```

## License

MIT
