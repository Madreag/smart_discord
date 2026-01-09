"""
Test Sliding Window Sessionizer

Verifies that messages are grouped correctly by:
1. Time window (15 minute gap)
2. Reply chain continuity
3. Channel boundaries
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from apps.bot.src.sessionizer import (
    Message,
    Session,
    sessionize_messages,
    process_channel_messages,
    SESSION_GAP_MINUTES,
)


def create_message(
    id: int,
    channel_id: int = 1,
    author_id: int = 1,
    content: str = "test",
    timestamp: datetime = None,
    reply_to_id: int = None,
) -> Message:
    """Helper to create test messages."""
    return Message(
        id=id,
        channel_id=channel_id,
        author_id=author_id,
        content=content,
        timestamp=timestamp or datetime.now(),
        reply_to_id=reply_to_id,
    )


def test_time_gap_breaks_session() -> tuple[int, int, list[str]]:
    """Test that time gaps > 15 minutes break sessions."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)
    
    messages = [
        create_message(1, timestamp=base_time),
        create_message(2, timestamp=base_time + timedelta(minutes=5)),
        create_message(3, timestamp=base_time + timedelta(minutes=10)),
        # Gap > 15 minutes
        create_message(4, timestamp=base_time + timedelta(minutes=30)),
        create_message(5, timestamp=base_time + timedelta(minutes=35)),
    ]
    
    sessions = sessionize_messages(messages)
    
    passed = 0
    failures = []
    
    # Should have 2 sessions
    if len(sessions) == 2:
        passed += 1
        print("✓ PASS: Time gap created 2 sessions")
    else:
        msg = f"✗ FAIL: Expected 2 sessions, got {len(sessions)}"
        print(msg)
        failures.append(msg)
    
    # First session should have 3 messages
    if sessions[0].message_ids == [1, 2, 3]:
        passed += 1
        print("✓ PASS: First session has correct messages")
    else:
        msg = f"✗ FAIL: First session wrong: {sessions[0].message_ids}"
        print(msg)
        failures.append(msg)
    
    # Second session should have 2 messages
    if sessions[1].message_ids == [4, 5]:
        passed += 1
        print("✓ PASS: Second session has correct messages")
    else:
        msg = f"✗ FAIL: Second session wrong: {sessions[1].message_ids}"
        print(msg)
        failures.append(msg)
    
    return (passed, 3, failures)


def test_channel_change_breaks_session() -> tuple[int, int, list[str]]:
    """Test that channel changes break sessions."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)
    
    messages = [
        create_message(1, channel_id=100, timestamp=base_time),
        create_message(2, channel_id=100, timestamp=base_time + timedelta(minutes=1)),
        # Different channel
        create_message(3, channel_id=200, timestamp=base_time + timedelta(minutes=2)),
        create_message(4, channel_id=200, timestamp=base_time + timedelta(minutes=3)),
    ]
    
    sessions = sessionize_messages(messages)
    
    passed = 0
    failures = []
    
    if len(sessions) == 2:
        passed += 1
        print("✓ PASS: Channel change created 2 sessions")
    else:
        msg = f"✗ FAIL: Expected 2 sessions, got {len(sessions)}"
        print(msg)
        failures.append(msg)
    
    if sessions[0].channel_id == 100 and sessions[1].channel_id == 200:
        passed += 1
        print("✓ PASS: Sessions have correct channel IDs")
    else:
        msg = f"✗ FAIL: Wrong channel IDs"
        print(msg)
        failures.append(msg)
    
    return (passed, 2, failures)


def test_reply_chain_break() -> tuple[int, int, list[str]]:
    """Test that reply chain breaks create new sessions."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)
    
    messages = [
        create_message(1, timestamp=base_time),
        create_message(2, timestamp=base_time + timedelta(minutes=1), reply_to_id=1),
        create_message(3, timestamp=base_time + timedelta(minutes=2), reply_to_id=2),
        # Reply to message outside session (simulating topic shift)
        create_message(4, timestamp=base_time + timedelta(minutes=3), reply_to_id=999),
        create_message(5, timestamp=base_time + timedelta(minutes=4)),
    ]
    
    sessions = sessionize_messages(messages)
    
    passed = 0
    failures = []
    
    if len(sessions) == 2:
        passed += 1
        print("✓ PASS: Reply chain break created 2 sessions")
    else:
        msg = f"✗ FAIL: Expected 2 sessions, got {len(sessions)}"
        print(msg)
        failures.append(msg)
    
    return (passed, 1, failures)


def test_continuous_conversation() -> tuple[int, int, list[str]]:
    """Test that continuous conversation stays in one session."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)
    
    messages = [
        create_message(i, timestamp=base_time + timedelta(minutes=i))
        for i in range(1, 11)
    ]
    
    sessions = sessionize_messages(messages)
    
    passed = 0
    failures = []
    
    if len(sessions) == 1:
        passed += 1
        print("✓ PASS: Continuous conversation in 1 session")
    else:
        msg = f"✗ FAIL: Expected 1 session, got {len(sessions)}"
        print(msg)
        failures.append(msg)
    
    if len(sessions[0].messages) == 10:
        passed += 1
        print("✓ PASS: Session has all 10 messages")
    else:
        msg = f"✗ FAIL: Expected 10 messages, got {len(sessions[0].messages)}"
        print(msg)
        failures.append(msg)
    
    return (passed, 2, failures)


def main() -> int:
    """Run all sessionizer tests."""
    print("=" * 60)
    print("Sliding Window Sessionizer Tests")
    print("=" * 60)
    
    total_passed = 0
    total_tests = 0
    all_failures = []
    
    print("\n--- Time Gap Breaks Session ---")
    p, t, f = test_time_gap_breaks_session()
    total_passed += p
    total_tests += t
    all_failures.extend(f)
    
    print("\n--- Channel Change Breaks Session ---")
    p, t, f = test_channel_change_breaks_session()
    total_passed += p
    total_tests += t
    all_failures.extend(f)
    
    print("\n--- Reply Chain Break ---")
    p, t, f = test_reply_chain_break()
    total_passed += p
    total_tests += t
    all_failures.extend(f)
    
    print("\n--- Continuous Conversation ---")
    p, t, f = test_continuous_conversation()
    total_passed += p
    total_tests += t
    all_failures.extend(f)
    
    print()
    print("=" * 60)
    print(f"Results: {total_passed}/{total_tests} passed")
    print("=" * 60)
    
    if total_passed == total_tests:
        print("✓ ALL SESSIONIZER TESTS PASSED")
        return 0
    else:
        print("✗ SESSIONIZER TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
