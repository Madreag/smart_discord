---
auto_execution_mode: 1
description: Shutdown Bot
---
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