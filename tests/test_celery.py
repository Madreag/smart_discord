#!/usr/bin/env python3
"""
Test Celery Task Queue functionality.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_celery_config():
    """Test Celery configuration."""
    print("Testing Celery Configuration...")
    print("=" * 50)
    
    from apps.bot.src.celery_config import celery_app
    
    # Check broker URL
    assert celery_app.conf.broker_url is not None
    print(f"✓ Broker URL: {celery_app.conf.broker_url}")
    
    # Check result backend
    assert celery_app.conf.result_backend is not None
    print(f"✓ Result backend: {celery_app.conf.result_backend}")
    
    # Check priority queues
    queues = celery_app.conf.task_queues
    assert len(queues) == 3
    queue_names = [q.name for q in queues]
    assert "high" in queue_names
    assert "default" in queue_names
    assert "low" in queue_names
    print(f"✓ Priority queues: {queue_names}")
    
    # Check reliability settings
    assert celery_app.conf.task_acks_late == True
    print("✓ task_acks_late enabled")
    
    assert celery_app.conf.task_reject_on_worker_lost == True
    print("✓ task_reject_on_worker_lost enabled")
    
    # Check timeouts
    assert celery_app.conf.task_soft_time_limit == 300
    assert celery_app.conf.task_time_limit == 600
    print("✓ Timeouts configured")
    
    print()
    return True


def test_task_definitions():
    """Test that all tasks are defined with proper decorators."""
    print("Testing Task Definitions...")
    print("=" * 50)
    
    from apps.bot.src.tasks import (
        index_messages,
        delete_message_vector,
        process_session,
        ask_query,
        batch_index_channel,
        get_queue_stats,
        process_dead_letter,
    )
    
    # Check tasks exist
    tasks = [
        ("index_messages", index_messages),
        ("delete_message_vector", delete_message_vector),
        ("process_session", process_session),
        ("ask_query", ask_query),
        ("batch_index_channel", batch_index_channel),
        ("get_queue_stats", get_queue_stats),
        ("process_dead_letter", process_dead_letter),
    ]
    
    for name, task in tasks:
        assert hasattr(task, 'delay'), f"{name} should have delay method"
        assert hasattr(task, 'apply_async'), f"{name} should have apply_async method"
        print(f"✓ {name} defined")
    
    # Check retry config on critical tasks
    assert index_messages.max_retries == 5
    print("✓ index_messages has max_retries=5")
    
    assert delete_message_vector.max_retries == 3
    print("✓ delete_message_vector has max_retries=3")
    
    print()
    return True


def test_task_routing():
    """Test task routing configuration."""
    print("Testing Task Routing...")
    print("=" * 50)
    
    from apps.bot.src.celery_config import celery_app
    
    routes = celery_app.conf.task_routes
    
    # High priority
    assert routes.get("delete_message_vector", {}).get("queue") == "high"
    print("✓ delete_message_vector → high queue")
    
    # Default priority
    assert routes.get("index_messages", {}).get("queue") == "default"
    print("✓ index_messages → default queue")
    
    # Low priority
    assert routes.get("batch_index_channel", {}).get("queue") == "low"
    print("✓ batch_index_channel → low queue")
    
    print()
    return True


def main():
    """Run all Celery tests."""
    print("\n" + "=" * 60)
    print("CELERY TASK QUEUE TESTS")
    print("=" * 60 + "\n")
    
    test1 = test_celery_config()
    test2 = test_task_definitions()
    test3 = test_task_routing()
    
    print("=" * 60)
    if test1 and test2 and test3:
        print("✓ All Celery tests passed!")
    else:
        print("✗ Some tests failed")
    print("=" * 60)
    
    return test1 and test2 and test3


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
