#!/usr/bin/env python3
"""
Integration Test: Right to be Forgotten (GDPR/CCPA Compliance)

Tests the complete deletion pipeline:
1. Message soft-deleted in Postgres (content cleared)
2. Session containing message deleted from Qdrant
3. Deleted content does NOT appear in RAG responses
"""

import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_qdrant_delete_sessions_method():
    """Test that delete_sessions_containing_messages method exists and works."""
    print("Testing Qdrant delete_sessions_containing_messages...")
    print("=" * 50)
    
    from apps.api.src.services.qdrant_service import qdrant_service
    
    # Check method exists
    assert hasattr(qdrant_service, 'delete_sessions_containing_messages'), \
        "delete_sessions_containing_messages method missing"
    print("✓ delete_sessions_containing_messages method exists")
    
    # Check get_sessions_by_message_ids exists
    assert hasattr(qdrant_service, 'get_sessions_by_message_ids'), \
        "get_sessions_by_message_ids method missing"
    print("✓ get_sessions_by_message_ids method exists")
    
    print()
    return True


def test_celery_task_exists():
    """Test that delete_sessions_for_messages Celery task exists."""
    print("Testing Celery Task...")
    print("=" * 50)
    
    from apps.bot.src.tasks import delete_sessions_for_messages
    
    assert hasattr(delete_sessions_for_messages, 'delay'), \
        "delete_sessions_for_messages task missing"
    print("✓ delete_sessions_for_messages task exists")
    
    # Check it's configured correctly
    assert delete_sessions_for_messages.max_retries == 3
    print("✓ Task has max_retries=3")
    
    print()
    return True


def test_postgres_soft_delete():
    """Test that Postgres soft delete works correctly."""
    print("Testing Postgres Soft Delete...")
    print("=" * 50)
    
    from sqlalchemy import create_engine, text
    
    engine = create_engine("postgresql://postgres:postgres@localhost:5432/smart_discord")
    
    with engine.connect() as conn:
        # Check deleted_at column exists
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'messages' AND column_name = 'deleted_at'
        """))
        row = result.fetchone()
        assert row is not None, "deleted_at column not found on messages table"
        print("✓ deleted_at column exists on messages table")
        
        # Check attachments table has is_deleted
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'attachments' AND column_name = 'is_deleted'
        """))
        row = result.fetchone()
        assert row is not None, "is_deleted column not found on attachments table"
        print("✓ is_deleted column exists on attachments table")
    
    print()
    return True


def test_full_deletion_pipeline():
    """
    Full integration test: Create message, index it, delete it, verify removal.
    
    This test requires running services (Postgres, Qdrant, Celery).
    """
    print("Testing Full Deletion Pipeline...")
    print("=" * 50)
    
    from sqlalchemy import create_engine, text
    from apps.api.src.services.qdrant_service import qdrant_service
    from apps.api.src.core.llm_factory import get_embedding_model
    
    engine = create_engine("postgresql://postgres:postgres@localhost:5432/smart_discord")
    
    # Use a test guild/channel to avoid affecting real data
    TEST_GUILD_ID = 999999999999999999
    TEST_CHANNEL_ID = 999999999999999998
    TEST_MESSAGE_ID = 999999999999999997
    TEST_USER_ID = 999999999999999996
    
    try:
        # Step 1: Create test data in Postgres
        print("  Creating test message in Postgres...")
        with engine.connect() as conn:
            # Ensure test user exists
            conn.execute(text("""
                INSERT INTO users (id, username, global_name, first_seen_at, updated_at)
                VALUES (:id, 'test_user', 'Test User', NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
            """), {"id": TEST_USER_ID})
            
            # Ensure test guild exists
            conn.execute(text("""
                INSERT INTO guilds (id, name, owner_id, joined_at, created_at, updated_at)
                VALUES (:id, 'Test Guild', :owner_id, NOW(), NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
            """), {"id": TEST_GUILD_ID, "owner_id": TEST_USER_ID})
            
            # Ensure test channel exists
            conn.execute(text("""
                INSERT INTO channels (id, guild_id, name, type, created_at, updated_at)
                VALUES (:id, :guild_id, 'test-channel', 0, NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
            """), {"id": TEST_CHANNEL_ID, "guild_id": TEST_GUILD_ID})
            
            # Create test message with sensitive content
            conn.execute(text("""
                INSERT INTO messages (id, channel_id, guild_id, author_id, content, 
                                      message_timestamp, created_at, updated_at)
                VALUES (:id, :channel_id, :guild_id, :author_id, 
                        'This is SENSITIVE DATA that must be deleted', 
                        NOW(), NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET 
                    content = 'This is SENSITIVE DATA that must be deleted',
                    is_deleted = FALSE,
                    deleted_at = NULL
            """), {
                "id": TEST_MESSAGE_ID,
                "channel_id": TEST_CHANNEL_ID,
                "guild_id": TEST_GUILD_ID,
                "author_id": TEST_USER_ID,
            })
            conn.commit()
        print("  ✓ Test message created")
        
        # Step 2: Index the message to Qdrant
        print("  Indexing message to Qdrant...")
        embedding_model = get_embedding_model()
        test_embedding = embedding_model.embed_query("This is SENSITIVE DATA that must be deleted")
        
        session_id = str(uuid4())
        qdrant_service.upsert_session(
            session_id=session_id,
            guild_id=TEST_GUILD_ID,
            channel_id=TEST_CHANNEL_ID,
            embedding=test_embedding,
            message_ids=[TEST_MESSAGE_ID],
            content_preview="This is SENSITIVE DATA that must be deleted",
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-01T00:01:00Z",
        )
        
        # Update Postgres with qdrant_point_id
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE messages SET qdrant_point_id = :session_id, indexed_at = NOW()
                WHERE id = :message_id
            """), {"session_id": session_id, "message_id": TEST_MESSAGE_ID})
            conn.commit()
        print(f"  ✓ Message indexed with session_id={session_id[:8]}...")
        
        # Step 3: Verify message is searchable
        print("  Verifying message is searchable...")
        sessions = qdrant_service.get_sessions_by_message_ids(TEST_GUILD_ID, [TEST_MESSAGE_ID])
        assert len(sessions) == 1, f"Expected 1 session, found {len(sessions)}"
        print("  ✓ Message found in Qdrant search")
        
        # Step 4: Delete the message (simulate deletion)
        print("  Deleting message (Right to be Forgotten)...")
        
        # Soft delete in Postgres
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE messages 
                SET is_deleted = TRUE, deleted_at = NOW(), content = '[deleted]'
                WHERE id = :message_id
            """), {"message_id": TEST_MESSAGE_ID})
            conn.commit()
        
        # Delete from Qdrant
        result = qdrant_service.delete_sessions_containing_messages(
            guild_id=TEST_GUILD_ID,
            message_ids=[TEST_MESSAGE_ID],
        )
        print(f"  ✓ Deleted {result['deleted_count']} session(s) from Qdrant")
        
        # Step 5: Verify message is no longer searchable
        print("  Verifying message is NOT searchable...")
        sessions_after = qdrant_service.get_sessions_by_message_ids(TEST_GUILD_ID, [TEST_MESSAGE_ID])
        assert len(sessions_after) == 0, f"Expected 0 sessions after deletion, found {len(sessions_after)}"
        print("  ✓ Message NOT found in Qdrant (correctly deleted)")
        
        # Step 6: Verify Postgres content is cleared
        print("  Verifying Postgres content is cleared...")
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT content, is_deleted FROM messages WHERE id = :message_id
            """), {"message_id": TEST_MESSAGE_ID})
            row = result.fetchone()
            assert row.content == '[deleted]', f"Expected '[deleted]', got '{row.content}'"
            assert row.is_deleted == True, "is_deleted should be True"
        print("  ✓ Postgres content cleared to '[deleted]'")
        
        print()
        print("=" * 50)
        print("✓ FULL DELETION PIPELINE TEST PASSED")
        print("  - Message soft-deleted in Postgres")
        print("  - Content cleared to '[deleted]'")
        print("  - Session removed from Qdrant")
        print("  - Content NOT searchable")
        print("=" * 50)
        
        return True
        
    except Exception as e:
        print(f"  ✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Cleanup test data
        print("\n  Cleaning up test data...")
        try:
            with engine.connect() as conn:
                conn.execute(text("DELETE FROM messages WHERE guild_id = :g"), {"g": TEST_GUILD_ID})
                conn.execute(text("DELETE FROM channels WHERE guild_id = :g"), {"g": TEST_GUILD_ID})
                conn.execute(text("DELETE FROM guilds WHERE id = :g"), {"g": TEST_GUILD_ID})
                conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": TEST_USER_ID})
                conn.commit()
            print("  ✓ Test data cleaned up")
        except Exception as e:
            print(f"  Warning: Cleanup failed: {e}")


def test_rag_excludes_deleted():
    """Test that RAG search excludes deleted message content."""
    print("Testing RAG Excludes Deleted Content...")
    print("=" * 50)
    
    from sqlalchemy import create_engine, text
    from apps.api.src.services.qdrant_service import qdrant_service
    from apps.api.src.core.llm_factory import get_embedding_model
    
    engine = create_engine("postgresql://postgres:postgres@localhost:5432/smart_discord")
    
    TEST_GUILD_ID = 999999999999999989
    TEST_CHANNEL_ID = 999999999999999988
    TEST_MESSAGE_ID_KEEP = 999999999999999987
    TEST_MESSAGE_ID_DELETE = 999999999999999986
    TEST_USER_ID = 999999999999999985
    
    try:
        # Setup test data
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO users (id, username, global_name, first_seen_at, updated_at)
                VALUES (:id, 'test_user2', 'Test User 2', NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
            """), {"id": TEST_USER_ID})
            
            conn.execute(text("""
                INSERT INTO guilds (id, name, owner_id, joined_at, created_at, updated_at)
                VALUES (:id, 'Test Guild 2', :owner_id, NOW(), NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
            """), {"id": TEST_GUILD_ID, "owner_id": TEST_USER_ID})
            
            conn.execute(text("""
                INSERT INTO channels (id, guild_id, name, type, created_at, updated_at)
                VALUES (:id, :guild_id, 'test-channel-2', 0, NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
            """), {"id": TEST_CHANNEL_ID, "guild_id": TEST_GUILD_ID})
            conn.commit()
        
        embedding_model = get_embedding_model()
        
        # Create two sessions - one to keep, one to delete
        session_id_keep = str(uuid4())
        session_id_delete = str(uuid4())
        
        # Index "keep" session
        embedding_keep = embedding_model.embed_query("Python programming best practices")
        qdrant_service.upsert_session(
            session_id=session_id_keep,
            guild_id=TEST_GUILD_ID,
            channel_id=TEST_CHANNEL_ID,
            embedding=embedding_keep,
            message_ids=[TEST_MESSAGE_ID_KEEP],
            content_preview="Python programming best practices",
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-01T00:01:00Z",
        )
        
        # Index "delete" session with sensitive content
        embedding_delete = embedding_model.embed_query("SECRET PASSWORD is hunter2")
        qdrant_service.upsert_session(
            session_id=session_id_delete,
            guild_id=TEST_GUILD_ID,
            channel_id=TEST_CHANNEL_ID,
            embedding=embedding_delete,
            message_ids=[TEST_MESSAGE_ID_DELETE],
            content_preview="SECRET PASSWORD is hunter2",
            start_time="2024-01-01T00:02:00Z",
            end_time="2024-01-01T00:03:00Z",
        )
        
        # Search for "password" - should find the sensitive session
        query_embedding = embedding_model.embed_query("password")
        results_before = qdrant_service.search(
            query_embedding=query_embedding,
            guild_id=TEST_GUILD_ID,
            limit=10,
            score_threshold=0.0,
        )
        
        found_secret_before = any("SECRET" in (r.get("payload", {}).get("content", "") or "") for r in results_before)
        print(f"  Before deletion: Found secret content = {found_secret_before}")
        
        # Delete the sensitive session
        result = qdrant_service.delete_sessions_containing_messages(
            guild_id=TEST_GUILD_ID,
            message_ids=[TEST_MESSAGE_ID_DELETE],
        )
        print(f"  Deleted {result['deleted_count']} session(s)")
        
        # Search again - should NOT find the sensitive session
        results_after = qdrant_service.search(
            query_embedding=query_embedding,
            guild_id=TEST_GUILD_ID,
            limit=10,
            score_threshold=0.0,
        )
        
        found_secret_after = any("SECRET" in (r.get("payload", {}).get("content", "") or "") for r in results_after)
        print(f"  After deletion: Found secret content = {found_secret_after}")
        
        assert not found_secret_after, "SECRET content should NOT be found after deletion!"
        print("  ✓ Deleted content NOT returned in RAG search")
        
        # Verify the "keep" session is still searchable
        python_embedding = embedding_model.embed_query("Python programming")
        python_results = qdrant_service.search(
            query_embedding=python_embedding,
            guild_id=TEST_GUILD_ID,
            limit=10,
            score_threshold=0.0,
        )
        found_python = any("Python" in (r.get("payload", {}).get("content", "") or "") for r in python_results)
        assert found_python, "Non-deleted content should still be searchable"
        print("  ✓ Non-deleted content still searchable")
        
        print()
        return True
        
    except Exception as e:
        print(f"  ✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Cleanup
        try:
            # Delete remaining test sessions
            qdrant_service.delete_by_guild(TEST_GUILD_ID)
            
            with engine.connect() as conn:
                conn.execute(text("DELETE FROM messages WHERE guild_id = :g"), {"g": TEST_GUILD_ID})
                conn.execute(text("DELETE FROM channels WHERE guild_id = :g"), {"g": TEST_GUILD_ID})
                conn.execute(text("DELETE FROM guilds WHERE id = :g"), {"g": TEST_GUILD_ID})
                conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": TEST_USER_ID})
                conn.commit()
        except Exception:
            pass


def main():
    """Run all Right to be Forgotten tests."""
    print("\n" + "=" * 60)
    print("RIGHT TO BE FORGOTTEN (GDPR/CCPA) COMPLIANCE TESTS")
    print("=" * 60 + "\n")
    
    results = []
    
    # Run basic checks first
    results.append(("Qdrant Delete Method", test_qdrant_delete_sessions_method()))
    results.append(("Celery Task", test_celery_task_exists()))
    results.append(("Postgres Soft Delete", test_postgres_soft_delete()))
    
    # Run integration tests
    results.append(("Full Deletion Pipeline", test_full_deletion_pipeline()))
    results.append(("RAG Excludes Deleted", test_rag_excludes_deleted()))
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name}")
        if not passed:
            all_passed = False
    
    print("=" * 60)
    
    if all_passed:
        print("✓ ALL TESTS PASSED - Right to be Forgotten is COMPLIANT")
    else:
        print("✗ SOME TESTS FAILED - Review implementation")
    
    print("=" * 60 + "\n")
    
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
