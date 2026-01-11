---
auto_execution_mode: 1
description: Startup Bot
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