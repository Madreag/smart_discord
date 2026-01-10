# Startup Guide

Quick reference for starting all services.

## Prerequisites

Ensure these are installed:
- Python 3.11+ with venv at `.venv/`
- Node.js 18+ with pnpm
- PostgreSQL running with `smart_discord` database
- Redis (installed via `sudo apt install redis-server`)

---

## Quick Start (All Services)

Run these in separate terminals:

### Terminal 1: Qdrant (Vector DB)
```bash
cd tools/qdrant && ./qdrant
```

### Terminal 2: API Server
```bash
source .venv/bin/activate
uvicorn apps.api.src.main:app --port 8000 --reload
```

### Terminal 3: Celery Worker
```bash
source .venv/bin/activate
celery -A apps.bot.src.tasks worker -Q high,default,low --loglevel=info
```

### Terminal 4: Discord Bot
```bash
source .venv/bin/activate
python apps/bot/src/bot.py
```

### Terminal 5: Dashboard (Optional)
```bash
pnpm dev:web
```

---

## Service URLs

| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| Dashboard | http://localhost:3000 |
| Qdrant | http://localhost:6333 |
| Flower (Celery Monitor) | http://localhost:5555 |

---

## One-Liner Start Script

Create `start_all.sh`:
```bash
#!/bin/bash
# Start all services in background

# Qdrant
cd tools/qdrant && ./qdrant &

# Redis (if not running as service)
redis-server --daemonize yes

# API
source .venv/bin/activate
uvicorn apps.api.src.main:app --port 8000 &

# Celery
celery -A apps.bot.src.tasks worker -Q high,default,low --loglevel=info &

# Bot
python apps/bot/src/bot.py &

# Dashboard
pnpm dev:web &

echo "All services started!"
```

---

## Health Checks

```bash
# API
curl http://localhost:8000/health

# Qdrant
curl http://localhost:6333/collections

# Redis
redis-cli ping
```

---

## Shutdown

```bash
# Kill all Python processes
pkill -f "python.*bot"
pkill -f "uvicorn"
pkill -f "celery"

# Stop Qdrant
pkill -f "qdrant"

# Stop Dashboard
pkill -f "next"
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| API won't start | Check if port 8000 is in use: `lsof -i :8000` |
| Qdrant connection refused | Start Qdrant first, then restart API |
| Celery can't connect | Ensure Redis is running: `redis-cli ping` |
| Bot duplicate responses | Kill all bot processes: `pkill -f "python.*bot"` |
| Dashboard auth error | Ensure API is running on port 8000 |
