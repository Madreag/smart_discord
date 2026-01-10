#!/usr/bin/env python3
"""
Test Semantic Chunking functionality.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from apps.bot.src.sessionizer import Message
from apps.bot.src.hybrid_sessionizer import hybrid_sessionize


def test_hybrid_sessionizer():
    """Test hybrid sessionizer with sample messages."""
    print("Testing Hybrid Sessionizer...")
    print("=" * 50)
    
    # Create test messages with different topics
    base_time = datetime.now()
    
    messages = [
        # Topic 1: Python programming
        Message(id=1, channel_id=100, author_id=1, content="Hey, I'm learning Python today!", timestamp=base_time),
        Message(id=2, channel_id=100, author_id=2, content="Python is great for beginners. Start with variables and functions.", timestamp=base_time + timedelta(minutes=1)),
        Message(id=3, channel_id=100, author_id=1, content="What IDE do you recommend for Python development?", timestamp=base_time + timedelta(minutes=2)),
        Message(id=4, channel_id=100, author_id=2, content="VSCode or PyCharm are both excellent choices for Python.", timestamp=base_time + timedelta(minutes=3)),
        
        # Topic 2: Gaming (different topic, but within time window)
        Message(id=5, channel_id=100, author_id=3, content="Anyone playing the new Zelda game?", timestamp=base_time + timedelta(minutes=5)),
        Message(id=6, channel_id=100, author_id=4, content="Yes! The open world is amazing. Spent 100 hours already.", timestamp=base_time + timedelta(minutes=6)),
        Message(id=7, channel_id=100, author_id=3, content="What's the best way to defeat the final boss?", timestamp=base_time + timedelta(minutes=7)),
        
        # Topic 3: Food (another topic shift)
        Message(id=8, channel_id=100, author_id=1, content="I'm hungry. Anyone know a good pizza place?", timestamp=base_time + timedelta(minutes=9)),
        Message(id=9, channel_id=100, author_id=5, content="Try Mario's Pizza on Main Street. Best pepperoni in town!", timestamp=base_time + timedelta(minutes=10)),
        Message(id=10, channel_id=100, author_id=1, content="Thanks! I'll order from there tonight.", timestamp=base_time + timedelta(minutes=11)),
        
        # Back to programming
        Message(id=11, channel_id=100, author_id=2, content="Back to Python - have you tried async/await yet?", timestamp=base_time + timedelta(minutes=12)),
        Message(id=12, channel_id=100, author_id=1, content="Not yet, but I heard it's important for web development.", timestamp=base_time + timedelta(minutes=13)),
    ]
    
    print(f"Input: {len(messages)} messages (multiple topic shifts)")
    print()
    
    # Test with semantic splitting enabled
    sessions = hybrid_sessionize(
        messages,
        semantic_split_threshold=5,  # Lower threshold to trigger semantic splitting
        min_session_size=2,
        max_session_size=20,
    )
    
    print(f"Output: {len(sessions)} sessions")
    print()
    
    for i, session in enumerate(sessions, 1):
        print(f"Session {i}:")
        print(f"  Messages: {len(session.messages)}")
        print(f"  IDs: {session.message_ids}")
        print(f"  Preview: \"{session.messages[0].content[:50]}...\"")
        print()
    
    print("=" * 50)
    
    # Verify we got multiple sessions (topic detection worked)
    if len(sessions) > 1:
        print("✓ Semantic chunking successfully detected topic shifts!")
    else:
        print("⚠ Only one session created - may need threshold tuning")
    
    return len(sessions) > 1


if __name__ == "__main__":
    success = test_hybrid_sessionizer()
    sys.exit(0 if success else 1)
