#!/usr/bin/env python3
"""
Test Message Edit/Delete Event Handlers.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_delete_handler_exists():
    """Test that delete handler is properly defined."""
    print("Testing Delete Handler...")
    print("=" * 50)
    
    # Import bot module to check handler exists
    import apps.bot.src.bot as bot_module
    
    # Check on_raw_message_delete exists
    assert hasattr(bot_module, 'on_raw_message_delete') or \
           any('on_raw_message_delete' in str(listener) for listener in bot_module.bot.extra_events.get('on_raw_message_delete', []))
    print("✓ on_raw_message_delete handler defined")
    
    # Check on_raw_bulk_message_delete exists
    assert hasattr(bot_module, 'on_raw_bulk_message_delete') or \
           any('on_raw_bulk_message_delete' in str(listener) for listener in bot_module.bot.extra_events.get('on_raw_bulk_message_delete', []))
    print("✓ on_raw_bulk_message_delete handler defined")
    
    print()
    return True


def test_edit_handler_exists():
    """Test that edit handler is properly defined."""
    print("Testing Edit Handler...")
    print("=" * 50)
    
    import apps.bot.src.bot as bot_module
    
    # Check on_raw_message_edit exists
    assert hasattr(bot_module, 'on_raw_message_edit') or \
           any('on_raw_message_edit' in str(listener) for listener in bot_module.bot.extra_events.get('on_raw_message_edit', []))
    print("✓ on_raw_message_edit handler defined")
    
    print()
    return True


def test_delete_task_exists():
    """Test that delete task is properly defined."""
    print("Testing Delete Task...")
    print("=" * 50)
    
    from apps.bot.src.tasks import delete_message_vector
    
    assert hasattr(delete_message_vector, 'delay')
    assert hasattr(delete_message_vector, 'apply_async')
    print("✓ delete_message_vector task defined")
    
    # Check retry config
    assert delete_message_vector.max_retries == 3
    print("✓ delete_message_vector has max_retries=3")
    
    print()
    return True


def test_qdrant_delete_method():
    """Test that Qdrant service has delete method."""
    print("Testing Qdrant Delete Method...")
    print("=" * 50)
    
    from apps.api.src.services.qdrant_service import qdrant_service
    
    assert hasattr(qdrant_service, 'delete_by_session_id')
    print("✓ delete_by_session_id method exists")
    
    assert hasattr(qdrant_service, 'delete_by_guild')
    print("✓ delete_by_guild method exists")
    
    print()
    return True


def test_db_soft_delete():
    """Test that soft delete SQL works correctly."""
    print("Testing Database Soft Delete...")
    print("=" * 50)
    
    from sqlalchemy import create_engine, text
    
    engine = create_engine("postgresql://postgres:postgres@localhost:5432/smart_discord")
    
    with engine.connect() as conn:
        # Check is_deleted column exists
        result = conn.execute(text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'messages' AND column_name = 'is_deleted'
        """))
        row = result.fetchone()
        assert row is not None, "is_deleted column not found"
        print(f"✓ is_deleted column exists (type: {row.data_type})")
        
        # Check qdrant_point_id column exists
        result = conn.execute(text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'messages' AND column_name = 'qdrant_point_id'
        """))
        row = result.fetchone()
        assert row is not None, "qdrant_point_id column not found"
        print(f"✓ qdrant_point_id column exists (type: {row.data_type})")
    
    print()
    return True


def main():
    """Run all message event tests."""
    print("\n" + "=" * 60)
    print("MESSAGE EDIT/DELETE EVENT TESTS")
    print("=" * 60 + "\n")
    
    results = []
    
    results.append(("Delete Handler", test_delete_handler_exists()))
    results.append(("Edit Handler", test_edit_handler_exists()))
    results.append(("Delete Task", test_delete_task_exists()))
    results.append(("Qdrant Delete", test_qdrant_delete_method()))
    results.append(("DB Soft Delete", test_db_soft_delete()))
    
    print("=" * 60)
    all_passed = all(r[1] for r in results)
    if all_passed:
        print("✓ All message event tests passed!")
    else:
        failed = [r[0] for r in results if not r[1]]
        print(f"✗ Failed tests: {failed}")
    print("=" * 60)
    
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
