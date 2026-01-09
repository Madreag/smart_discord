# REPORT 8: Celery/Redis Task Queue (Scaffolded → Production)

> **Priority**: Scaffolded Implementation  
> **Effort**: 1-2 days to complete  
> **Status**: Tasks defined, logic incomplete

---

## 1. Executive Summary

Celery tasks are defined in `apps/bot/src/tasks.py` but contain `# TODO` placeholders. The infrastructure (Redis, Celery worker) is configured in `docker-compose.yml` but the actual task logic is missing.

**✅ Implemented**:
- Celery app configuration
- Redis as broker/backend
- Task definitions with signatures
- Docker service for worker

**❌ Missing**:
- Actual task implementations
- Retry logic with backoff
- Dead letter queue handling
- Priority queues
- Monitoring (Flower)

---

## 2. Current State Analysis

### Existing Configuration

```python
# apps/bot/src/tasks.py (current)
celery_app = Celery(
    "smart_discord",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/1",
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,
    worker_prefetch_multiplier=1,
)
```

### Tasks with TODO

```python
@celery_app.task(bind=True, name="index_messages")
def index_messages(self, payload_dict: dict) -> dict:
    # TODO: Implement actual indexing logic
    return {"status": "success", ...}  # Does nothing!
```

---

## 3. Production Configuration

### Enhanced Celery Config

```python
# apps/bot/src/celery_config.py
"""
Production Celery Configuration

Reference: https://oneuptime.com/blog/post/2025-01-06-python-celery-redis-job-queue/view
"""

import os
from celery import Celery
from kombu import Queue, Exchange

# Initialize app
celery_app = Celery("smart_discord")

# Broker settings
celery_app.conf.broker_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
celery_app.conf.result_backend = os.environ.get("REDIS_URL", "redis://localhost:6379/1")

# Serialization
celery_app.conf.task_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.result_serializer = "json"
celery_app.conf.timezone = "UTC"
celery_app.conf.enable_utc = True

# Reliability settings
celery_app.conf.task_acks_late = True  # Ack after task completes (not before)
celery_app.conf.task_reject_on_worker_lost = True  # Re-queue if worker dies
celery_app.conf.worker_prefetch_multiplier = 1  # Fair scheduling

# Concurrency
celery_app.conf.worker_concurrency = int(os.getenv("CELERY_CONCURRENCY", 4))

# Memory management
celery_app.conf.worker_max_tasks_per_child = 1000  # Restart worker after N tasks
celery_app.conf.worker_max_memory_per_child = 200000  # 200MB limit

# Timeouts
celery_app.conf.task_soft_time_limit = 300  # 5 min soft limit (raises exception)
celery_app.conf.task_time_limit = 600  # 10 min hard limit (kills task)

# Result backend
celery_app.conf.result_expires = 86400  # 24 hours

# Priority queues
celery_app.conf.task_queues = (
    Queue("high", Exchange("high"), routing_key="high"),
    Queue("default", Exchange("default"), routing_key="default"),
    Queue("low", Exchange("low"), routing_key="low"),
)
celery_app.conf.task_default_queue = "default"
celery_app.conf.task_default_exchange = "default"
celery_app.conf.task_default_routing_key = "default"

# Task routing
celery_app.conf.task_routes = {
    "index_session": {"queue": "default"},
    "delete_message_vectors": {"queue": "high"},  # Deletions are priority
    "batch_index_channel": {"queue": "low"},
    "build_guild_graph": {"queue": "low"},
}
```

---

## 4. Complete Task Implementations

### Index Session Task

```python
# apps/bot/src/tasks.py

@celery_app.task(
    bind=True,
    name="index_session",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def index_session(
    self,
    guild_id: int,
    channel_id: int,
    channel_name: str,
    session_id: str,
    message_ids: list[int],
    start_time: str,
    end_time: str,
) -> dict:
    """
    Index a message session to Qdrant.
    
    With automatic retry and exponential backoff.
    """
    import asyncio
    from apps.api.src.services.embedding_service import generate_embedding
    from apps.api.src.services.enrichment_service import enrich_session
    from apps.api.src.services.qdrant_service import qdrant_service
    
    print(f"[TASK] index_session: {session_id} ({len(message_ids)} messages)")
    
    engine = get_db_engine()
    
    # Fetch messages
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT m.id, m.content, m.message_timestamp, u.username, u.global_name
            FROM messages m
            JOIN users u ON m.author_id = u.id
            WHERE m.id = ANY(:ids) AND m.guild_id = :guild_id AND m.is_deleted = FALSE
            ORDER BY m.message_timestamp
        """), {"ids": message_ids, "guild_id": guild_id})
        rows = result.fetchall()
    
    if not rows:
        return {"status": "skipped", "reason": "no_messages"}
    
    # Enrich and embed
    messages = [{
        "content": r.content,
        "author_name": r.global_name or r.username,
        "timestamp": r.message_timestamp,
    } for r in rows]
    
    enriched_text = enrich_session(messages, channel_name)
    embedding = generate_embedding(enriched_text)
    
    # Upsert to Qdrant
    asyncio.run(qdrant_service.upsert_session(
        session_id=session_id,
        guild_id=guild_id,
        channel_id=channel_id,
        embedding=embedding,
        message_ids=message_ids,
        content_preview=enriched_text[:500],
        start_time=start_time,
        end_time=end_time,
    ))
    
    # Update Postgres
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE message_sessions
            SET qdrant_point_id = :point_id
            WHERE id = :session_id
        """), {"point_id": session_id, "session_id": session_id})
        conn.commit()
    
    return {
        "status": "success",
        "session_id": session_id,
        "message_count": len(message_ids),
    }
```

### Delete with Priority

```python
@celery_app.task(
    bind=True,
    name="delete_message_vectors",
    queue="high",  # Priority queue
    max_retries=3,
)
def delete_message_vectors(
    self,
    guild_id: int,
    message_ids: list[int],
) -> dict:
    """
    Delete vectors for messages (Right to be Forgotten).
    
    Runs in high-priority queue for fast processing.
    """
    import asyncio
    from apps.api.src.services.qdrant_service import qdrant_service
    
    print(f"[TASK] delete_message_vectors: {len(message_ids)} messages")
    
    deleted = asyncio.run(qdrant_service.delete_by_message_ids(guild_id, message_ids))
    
    return {
        "status": "success",
        "guild_id": guild_id,
        "deleted_count": deleted,
    }
```

### Batch Indexing (Low Priority)

```python
@celery_app.task(
    bind=True,
    name="batch_index_channel",
    queue="low",  # Low priority - background job
    time_limit=3600,  # 1 hour max
)
def batch_index_channel(
    self,
    guild_id: int,
    channel_id: int,
    channel_name: str,
    batch_size: int = 100,
) -> dict:
    """
    Batch index all unindexed messages in a channel.
    
    Runs in low-priority queue to not block real-time operations.
    """
    from apps.bot.src.sessionizer import sessionize_messages, Message
    from uuid import uuid4
    
    print(f"[TASK] batch_index_channel: {channel_name}")
    
    engine = get_db_engine()
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, content, author_id, message_timestamp, reply_to_id
            FROM messages
            WHERE guild_id = :g AND channel_id = :c
              AND is_deleted = FALSE AND qdrant_point_id IS NULL
            ORDER BY message_timestamp
            LIMIT :limit
        """), {"g": guild_id, "c": channel_id, "limit": batch_size})
        rows = result.fetchall()
    
    if not rows:
        return {"status": "complete", "indexed": 0}
    
    # Sessionize
    messages = [Message(
        id=r.id,
        channel_id=channel_id,
        author_id=r.author_id,
        content=r.content,
        timestamp=r.message_timestamp,
        reply_to_id=r.reply_to_id,
    ) for r in rows]
    
    sessions = sessionize_messages(messages)
    
    # Queue each session
    for session in sessions:
        if len(session.messages) >= 2:
            session_id = str(uuid4())
            index_session.apply_async(
                kwargs={
                    "guild_id": guild_id,
                    "channel_id": channel_id,
                    "channel_name": channel_name,
                    "session_id": session_id,
                    "message_ids": session.message_ids,
                    "start_time": session.start_time.isoformat(),
                    "end_time": session.end_time.isoformat(),
                },
                queue="default",
            )
    
    return {
        "status": "processing",
        "messages_found": len(rows),
        "sessions_queued": len(sessions),
    }
```

---

## 5. Dead Letter Queue Pattern

```python
# apps/bot/src/tasks.py

from celery.signals import task_failure

# Dead letter queue for failed tasks
DEAD_LETTER_QUEUE = "dead_letter"

@task_failure.connect
def handle_task_failure(sender=None, task_id=None, exception=None, args=None, kwargs=None, traceback=None, **kw):
    """
    Handle permanently failed tasks.
    
    Logs to dead letter queue for manual investigation.
    """
    import json
    import redis
    
    client = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
    
    failure_data = {
        "task_name": sender.name if sender else "unknown",
        "task_id": task_id,
        "args": args,
        "kwargs": kwargs,
        "exception": str(exception),
        "timestamp": datetime.utcnow().isoformat(),
    }
    
    # Push to dead letter queue
    client.lpush(DEAD_LETTER_QUEUE, json.dumps(failure_data))
    
    print(f"[DLQ] Task {task_id} failed permanently: {exception}")


@celery_app.task(name="process_dead_letter")
def process_dead_letter(limit: int = 10) -> dict:
    """
    Process items from dead letter queue.
    
    Can be used to retry or investigate failures.
    """
    import json
    import redis
    
    client = redis.from_url(os.environ.get("REDIS_URL"))
    
    processed = []
    for _ in range(limit):
        item = client.rpop(DEAD_LETTER_QUEUE)
        if not item:
            break
        processed.append(json.loads(item))
    
    return {
        "processed_count": len(processed),
        "items": processed,
    }
```

---

## 6. Monitoring with Flower

### Docker Compose Addition

```yaml
# docker-compose.yml (add Flower service)
  flower:
    image: mher/flower:0.9.7
    container_name: smart_discord_flower
    command: celery --broker=redis://redis:6379/0 flower --port=5555
    ports:
      - "5555:5555"
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - FLOWER_BASIC_AUTH=admin:password  # Set in production
    depends_on:
      - redis
```

### Prometheus Metrics

```python
# apps/bot/src/celery_config.py

# Enable Prometheus metrics
celery_app.conf.worker_send_task_events = True
celery_app.conf.task_send_sent_event = True

# Custom metrics endpoint (if using custom exporter)
@celery_app.task(name="get_queue_stats")
def get_queue_stats() -> dict:
    """Get queue statistics for monitoring."""
    import redis
    
    client = redis.from_url(os.environ.get("REDIS_URL"))
    
    queues = ["high", "default", "low", DEAD_LETTER_QUEUE]
    stats = {}
    
    for queue in queues:
        stats[queue] = client.llen(queue)
    
    return stats
```

---

## 7. Running Workers

### Development

```bash
# Single worker with all queues
celery -A apps.bot.src.tasks worker --loglevel=info

# With Celery Beat (for scheduled tasks)
celery -A apps.bot.src.tasks worker --beat --loglevel=info
```

### Production

```bash
# High-priority worker
celery -A apps.bot.src.tasks worker -Q high --concurrency=2 --loglevel=warning

# Default worker
celery -A apps.bot.src.tasks worker -Q default --concurrency=4 --loglevel=warning

# Low-priority worker (batch jobs)
celery -A apps.bot.src.tasks worker -Q low --concurrency=1 --loglevel=warning

# Beat scheduler (separate process)
celery -A apps.bot.src.tasks beat --loglevel=info
```

---

## 8. References

- [Celery Best Practices](https://docs.celeryq.dev/en/stable/userguide/tasks.html#best-practices)
- [OneUptime: Python Celery Redis Guide](https://oneuptime.com/blog/post/2025-01-06-python-celery-redis-job-queue/view)
- [Celery + FastAPI Production Guide](https://medium.com/@dewasheesh.rana/celery-redis-fastapi-the-ultimate-2025-production-guide)
- [Flower Monitoring](https://flower.readthedocs.io/)

---

## 9. Checklist

- [ ] Update `apps/bot/src/celery_config.py` with production settings
- [ ] Implement all task logic (remove TODOs)
- [ ] Add retry logic with exponential backoff
- [ ] Set up priority queues (high, default, low)
- [ ] Implement dead letter queue pattern
- [ ] Add Flower to `docker-compose.yml`
- [ ] Add Celery Beat for scheduled tasks
- [ ] Test worker restart scenarios
- [ ] Add monitoring/alerting for queue depth
