# 🧠 Smart Discord Bot

**Turn your Discord server into a searchable knowledge base.**

Your community generates thousands of messages. This bot makes them *useful* — ask questions in natural language and get instant, AI-powered answers from your server's history.

<p align="center">
  <img src="https://img.shields.io/badge/Discord-Bot-5865F2?logo=discord&logoColor=white" alt="Discord Bot">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Next.js-Dashboard-000000?logo=next.js&logoColor=white" alt="Next.js">
</p>

---

## 💡 What Can It Do?

```
You:  @bot What did we decide about the API redesign?
Bot:  Based on discussions in #dev on Jan 5-7, the team decided to:
      1. Use REST instead of GraphQL
      2. Add rate limiting (discussed by Alice)
      3. Deploy by end of month
      Sources: #dev (15 messages)
```

### ✨ Key Features

| | Feature | Description |
|---|---------|-------------|
| 🔍 | **Semantic Search** | Find conversations by *meaning*, not keywords |
| 📊 | **Natural Analytics** | "Who's most active?" "Messages this week?" |
| 📄 | **Document Search** | Upload PDFs, TXT, MD — they become searchable |
| 🖼️ | **Image Understanding** | Vision AI describes uploaded images |
| 🔒 | **Privacy First** | Delete a message → AI forgets it completely |
| 🌐 | **Multi-LLM** | OpenAI, Anthropic Claude, or xAI Grok |
| 📈 | **Live Dashboard** | Real-time stats, channel toggles, settings |
| ⚡ | **Background Processing** | Heavy tasks run async via Celery |

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+** and **Node.js 18+** 
- **PostgreSQL**, **Qdrant**, **Redis**

### 1. Install Dependencies

```bash
git clone <repo-url> && cd smart_discord

# Python
python3 -m venv .venv && source .venv/bin/activate
pip install -e packages/shared -e packages/database -e apps/api -e apps/bot
pip install psycopg2-binary pypdf httpx redis

# Node.js (for dashboard)
npm install -g pnpm && pnpm install
```

### 2. Set Up Databases

```bash
# PostgreSQL
sudo apt install -y postgresql postgresql-contrib redis-server
sudo service postgresql start && sudo service redis-server start
sudo -u postgres psql -c "CREATE DATABASE smart_discord;"
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'postgres';"

# Run all migrations
for f in packages/database/migrations/*.sql; do
  PGPASSWORD=postgres psql -h localhost -U postgres -d smart_discord -f "$f"
done
```

**Qdrant (Vector DB):**
```bash
docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant
# Or download binary: https://github.com/qdrant/qdrant/releases
```

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:
```env
# Required
DISCORD_TOKEN=your-bot-token
DISCORD_CLIENT_ID=your-client-id
DISCORD_CLIENT_SECRET=your-client-secret

# Choose ONE LLM provider
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Dashboard auth (generate: openssl rand -base64 32)
AUTH_SECRET=your-random-secret
```

### 4. Set Up Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications/)
2. Create application → Bot → Copy token
3. Enable **Privileged Gateway Intents**: ✅ SERVER MEMBERS, ✅ MESSAGE CONTENT
4. OAuth2 → URL Generator → Scopes: `bot`, `applications.commands`
5. Invite bot to your server

### 5. Run Services

```bash
# Terminal 1: API
source .venv/bin/activate
uvicorn apps.api.src.main:app --port 8000 --reload

# Terminal 2: Celery Worker (for background tasks)
source .venv/bin/activate
celery -A apps.bot.src.tasks worker -Q high,default,low --loglevel=info

# Terminal 3: Bot
source .venv/bin/activate
python apps/bot/src/bot.py

# Terminal 4: Dashboard (optional)
pnpm dev:web
```

### 6. Index Existing Messages

```bash
source .venv/bin/activate
python scripts/backfill_messages.py --guild-id YOUR_GUILD_ID --limit 1000
python scripts/index_to_qdrant.py --guild-id YOUR_GUILD_ID
```

> **Tip:** Use Docker Compose for production: `docker-compose up -d`

---

## 💬 Using the Bot

### Commands

| Method | Example |
|--------|---------|
| **@Mention** | `@bot what did we discuss about the API?` |
| **Slash** | `/ai question: who talks the most?` |
| **DM** | Direct message the bot for private conversations |

### Query Types (Auto-Routed)

The bot automatically detects what you're asking:

| Type | Examples | How It Works |
|------|----------|--------------|
| **Semantic Search** | "What did Alice say about the bug?" | Vector search in Qdrant |
| **Analytics** | "Most active user?", "Messages this week?" | Text-to-SQL on Postgres |
| **Document Search** | "What does the PDF say about X?" | Searches uploaded files |
| **General Knowledge** | "What is Python?" | Direct LLM response |
| **Web Search** | "Latest Node.js version?" | Tavily API |

### 📄 Document Support

Upload files to Discord — they automatically become searchable:

| Format | Processing |
|--------|------------|
| **PDF** | Text extraction via pypdf |
| **TXT/MD** | Direct text with semantic chunking |
| **Images** | Vision AI generates searchable description |

**Supported:** `.pdf`, `.txt`, `.md`, `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`  
**Blocked:** `.exe`, `.bat`, `.sh` (security)

---

## 📊 Dashboard

Visit `http://localhost:3000` and log in with Discord.

### Features

| Section | Description |
|---------|-------------|
| **Overview** | Total messages, indexed count, active users |
| **Indexing Progress** | Visual progress bars |
| **Activity Chart** | Message volume over 30 days |
| **Top Channels** | Most active channels with index status |
| **Channel Toggles** | Enable/disable indexing per channel |
| **Settings** | LLM provider, API keys, pre-prompts |

### Access Control

Only users with **Administrator** or **Manage Server** permission can access a guild's dashboard.

---

## ⚙️ Configuration

### LLM Providers

| Provider | Model | Environment Variable |
|----------|-------|---------------------|
| OpenAI | gpt-4o-mini | `OPENAI_API_KEY` |
| Anthropic | claude-sonnet-4-20250514 | `ANTHROPIC_API_KEY` |
| xAI | grok-beta | `XAI_API_KEY` |

### Runtime Configuration

Change LLM provider and API keys from the dashboard without restarting:
- Settings → LLM Provider
- Settings → API Keys

---

## 🔌 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/ask` | POST | Process query with routing |
| `/chat` | POST | DM conversation with memory |
| `/guilds/{id}/stats` | GET | Real-time guild statistics |
| `/guilds/{id}/stats/timeseries` | GET | Activity over time |
| `/guilds/{id}/stats/top-channels` | GET | Most active channels |
| `/guilds/{id}/channels` | GET | List channels |
| `/guilds/{id}/channels/{id}/index` | PATCH | Toggle indexing |
| `/settings/provider` | GET/PUT | LLM configuration |
| `/settings/api-keys` | GET/PUT | API key management |

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  Dashboard (Next.js 15)              http://localhost:3000     │
│  • Real-time analytics  • Channel toggles  • LLM settings      │
└────────────────────────────────────────────────────────────────┘
                                │
┌────────────────────────────────────────────────────────────────┐
│  Cognitive Layer (FastAPI)           http://localhost:8000     │
│  • Router Agent → Analytics / Vector RAG / Web Search          │
│  • Document Processor (PDF, Image, TXT)                        │
│  • Security Service (prompt injection, sanitization)           │
└────────────────────────────────────────────────────────────────┘
                                │
┌────────────────────────────────────────────────────────────────┐
│  Celery Workers                      (Background Processing)   │
│  • Document ingestion  • Vector indexing  • Retry with backoff │
│  • Priority queues: high → default → low                       │
└────────────────────────────────────────────────────────────────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          ▼                     ▼                     ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│    PostgreSQL    │  │      Qdrant      │  │       Redis      │
│  Source of Truth │  │  Semantic Index  │  │    Task Queue    │
│  • Messages      │  │  • Chat vectors  │  │  • Celery broker │
│  • Attachments   │  │  • Doc vectors   │  │  • Dead letter Q │
│  • Users/Guilds  │  │  • Hybrid filter │  │                  │
└──────────────────┘  └──────────────────┘  └──────────────────┘
          ▲
          │
┌────────────────────────────────────────────────────────────────┐
│  Discord Bot (discord.py)            (Gateway - Non-blocking)  │
│  • Message ingestion  • Attachment detection  • /ai commands   │
│  • Edit/Delete handlers (Right to be Forgotten)                │
└────────────────────────────────────────────────────────────────┘
```

### Key Design Principles

| Principle | Implementation |
|-----------|----------------|
| **No-Block Gateway** | Bot never downloads files; pushes URLs to Celery |
| **Hybrid Storage** | Postgres = source of truth, Qdrant = semantic index |
| **Dual Chunking** | Chat: sliding window (15min), Docs: recursive/semantic |
| **Right to be Forgotten** | Delete message → hard delete from Qdrant |
| **Multi-Tenancy** | All queries scoped by `guild_id` |

---

## 📁 Project Structure

```
smart_discord/
├── apps/
│   ├── api/                    # FastAPI Cognitive Layer
│   │   └── src/
│   │       ├── agents/         # Router, Analytics, RAG agents
│   │       ├── services/       # Qdrant, Document Processor, Security
│   │       └── main.py
│   ├── bot/                    # Discord Bot (Gateway)
│   │   └── src/
│   │       ├── bot.py          # Event handlers
│   │       ├── tasks.py        # Celery tasks
│   │       └── celery_config.py
│   └── web/                    # Next.js Dashboard
├── packages/
│   ├── database/
│   │   ├── migrations/         # SQL schema (001-004)
│   │   └── models.py           # SQLAlchemy ORM
│   └── shared/                 # Shared types (Python + TS)
├── scripts/
│   ├── backfill_messages.py    # Import historical messages
│   ├── index_to_qdrant.py      # Index to vector DB
│   └── verify_sync.py          # Check Postgres↔Qdrant sync
├── tests/
└── docker-compose.yml          # Full stack deployment
```

---

## 🔧 Troubleshooting

| Issue | Solution |
|-------|----------|
| "PrivilegedIntentsRequired" | Enable intents in Discord Developer Portal |
| "invalid x-api-key" | Check format: Anthropic=`sk-ant-`, OpenAI=`sk-` |
| Empty search results | Run `index_to_qdrant.py` to populate vectors |
| Duplicate bot responses | Kill all bot processes: `pkill -f "python.*bot"` |
| Sync degraded | Run `python scripts/verify_sync.py --guild-id X --repair` |
| Redis connection failed | `sudo service redis-server start` |

---

## 🧪 Tests

```bash
source .venv/bin/activate

# Core functionality
python tests/test_sessionizer.py          # Message sessionization
python tests/test_sql_validator.py        # SQL injection prevention
python tests/test_document_ingestion.py   # PDF/Image processing

# Infrastructure
python tests/test_celery.py               # Task queue
python tests/test_message_events.py       # Edit/Delete handlers
python tests/test_security.py             # Prompt injection
python tests/test_rate_limiter.py         # Rate limiting
```

---

## 🚢 Production Deployment

```bash
# Using Docker Compose
docker-compose up -d

# Services included:
# - PostgreSQL (port 5432)
# - Qdrant (port 6333)
# - Redis (port 6379)
# - API (port 8000)
# - Celery Worker
# - Flower Monitor (port 5555)
# - Dashboard (port 3000)
```

---

## 📝 License

MIT
