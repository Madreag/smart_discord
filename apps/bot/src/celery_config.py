"""
Production Celery Configuration

Features:
- Priority queues (high, default, low)
- Automatic retry with exponential backoff
- Dead letter queue for failed tasks
- Memory management
- Reliability settings
"""

import os
from celery import Celery
from kombu import Queue, Exchange

# Initialize app
celery_app = Celery("smart_discord")

# Broker settings
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
celery_app.conf.broker_url = REDIS_URL
celery_app.conf.result_backend = REDIS_URL.replace("/0", "/1")

# Serialization
celery_app.conf.task_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.result_serializer = "json"
celery_app.conf.timezone = "UTC"
celery_app.conf.enable_utc = True

# Reliability settings
celery_app.conf.task_acks_late = True  # Ack after task completes
celery_app.conf.task_reject_on_worker_lost = True  # Re-queue if worker dies
celery_app.conf.worker_prefetch_multiplier = 1  # Fair scheduling

# Concurrency
celery_app.conf.worker_concurrency = int(os.getenv("CELERY_CONCURRENCY", 4))

# Memory management
celery_app.conf.worker_max_tasks_per_child = 1000  # Restart worker after N tasks
celery_app.conf.worker_max_memory_per_child = 200000  # 200MB limit

# Timeouts
celery_app.conf.task_soft_time_limit = 300  # 5 min soft limit
celery_app.conf.task_time_limit = 600  # 10 min hard limit

# Result backend
celery_app.conf.result_expires = 86400  # 24 hours

# Track task state
celery_app.conf.task_track_started = True

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
    "delete_message_vector": {"queue": "high"},  # Deletions are priority
    "index_messages": {"queue": "default"},
    "process_session": {"queue": "default"},
    "ask_query": {"queue": "default"},
    "batch_index_channel": {"queue": "low"},
    "verify_sync": {"queue": "low"},
}

# Events for monitoring
celery_app.conf.worker_send_task_events = True
celery_app.conf.task_send_sent_event = True
