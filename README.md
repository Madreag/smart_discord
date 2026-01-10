# Smart Discord Bot

An intelligent Discord bot with **semantic search**, **analytics**, and a **real-time dashboard**. Ask questions about your server's history and get AI-powered answers.

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🤖 **AI Q&A** | Ask questions with `@bot` or `/ai` - answers from chat history |
| 📊 **Analytics** | "Who talks the most?", "Messages last week?" |
| 🔍 **Semantic Search** | Find conversations by meaning, not just keywords |
| 💬 **Conversation Memory** | Bot remembers current chat session |
| 🌐 **Multi-LLM** | OpenAI, Anthropic (Claude), or xAI (Grok) |
| 📈 **Real Dashboard** | Live stats, activity charts, channel management |
| 🔒 **RBAC** | Only server admins can access dashboard |

---

## 🚀 Quick Start

### Prerequisites

- **Node.js 18+** and **pnpm** (`npm install -g pnpm`)
- **Python 3.11+**
- **PostgreSQL** and **Qdrant**

### 1. Install Dependencies

```bash
git clone <repo-url> && cd smart_discord

# Node.js
pnpm install

# Python
python3 -m venv .venv
source .venv/bin/activate
pip install -e packages/shared -e packages/database -e apps/api -e apps/bot
pip install psycopg2-binary
```

### 2. Set Up Databases

**PostgreSQL:**
```bash
# Linux/WSL
sudo apt install -y postgresql postgresql-contrib
sudo service postgresql start
sudo -u postgres psql -c "CREATE DATABASE smart_discord;"
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'postgres';"
sudo -u postgres psql -d smart_discord -f packages/database/migrations/001_initial_schema.sql
```

**Qdrant (Vector DB):**
```bash
mkdir -p tools/qdrant && cd tools/qdrant
curl -LO https://github.com/qdrant/qdrant/releases/download/v1.12.1/qdrant-x86_64-unknown-linux-gnu.tar.gz
tar -xzf qdrant-*.tar.gz && rm qdrant-*.tar.gz
./qdrant  # Runs on localhost:6333
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
# Terminal 1: Qdrant
cd tools/qdrant && ./qdrant

# Terminal 2: API
source .venv/bin/activate
uvicorn apps.api.src.main:app --port 8000 --reload

# Terminal 3: Bot
source .venv/bin/activate
python -m apps.bot.src.bot

# Terminal 4: Dashboard (optional)
pnpm dev:web
```

### 6. Index Existing Messages

```bash
source .venv/bin/activate
python scripts/backfill_messages.py --guild-id YOUR_GUILD_ID --limit 1000
python scripts/index_to_qdrant.py --guild-id YOUR_GUILD_ID
```

---

## 💬 Using the Bot

### Commands

| Method | Example |
|--------|---------|
| **Mention** | `@bot what did we discuss about the API?` |
| **Slash** | `/ai question: who talks the most?` |

### Query Types (Auto-Detected)

| Type | Examples |
|------|----------|
| **Semantic Search** | "What did Alice say about the bug?" |
| **Analytics** | "How many messages this week?", "Most active user?" |
| **General Knowledge** | "What is Python?", "Capital of France?" |
| **Web Search** | "Latest Node.js version?" (requires Tavily API) |

### Conversation Memory

The bot remembers your current chat session:
- "What did you just tell me?"
- "Summarize our conversation"
- "You mentioned something about..."

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
┌─────────────────────────────────────────────────────────────┐
│  Dashboard (Next.js 15)          http://localhost:3000      │
│  • Real analytics  • Channel toggles  • LLM settings        │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  API (FastAPI)                   http://localhost:8000      │
│  • Router Agent → Analytics / Vector RAG / Web Search       │
│  • Conversation Memory  • Guild Stats                       │
└─────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   PostgreSQL    │  │     Qdrant      │  │      Redis      │
│   (Messages)    │  │   (Vectors)     │  │  (Task Queue)   │
└─────────────────┘  └─────────────────┘  └─────────────────┘
          ▲
          │
┌─────────────────────────────────────────────────────────────┐
│  Discord Bot (discord.py)                                   │
│  • Message ingestion  • @mention handler  • /ai commands    │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
smart_discord/
├── apps/
│   ├── api/         # FastAPI backend
│   ├── bot/         # Discord bot
│   └── web/         # Next.js dashboard
├── packages/
│   ├── database/    # Migrations, models
│   └── shared/      # Shared types
├── scripts/
│   ├── backfill_messages.py    # Import historical messages
│   └── index_to_qdrant.py      # Index messages to vector DB
└── tests/
```

---

## 🔧 Troubleshooting

| Issue | Solution |
|-------|----------|
| "PrivilegedIntentsRequired" | Enable intents in Discord Developer Portal |
| "invalid x-api-key" | Check key format: Anthropic=`sk-ant-`, OpenAI=`sk-` |
| Empty search results | Run `index_to_qdrant.py` to populate vectors |
| PostgreSQL not running | `sudo service postgresql start` |
| Qdrant not running | `cd tools/qdrant && ./qdrant` |

---

## 🧪 Tests

```bash
source .venv/bin/activate
python3 tests/repro_routing.py        # Router Agent
python3 tests/test_sql_validator.py   # SQL Security
python3 tests/test_sessionizer.py     # Sessionizer
```

---

## 📝 License

MIT
