"""
RED PHASE: Router Agent Intent Classification Test

This test MUST FAIL initially because the Router Agent is not implemented.
After GREEN PHASE implementation, this test MUST PASS.

Test Cases:
1. "Who spoke most?" → analytics_db (statistical query on messages table)
2. "What are the main complaints?" → vector_rag (semantic search)
3. "What is the latest news about Python 3.13?" → web_search (external info)
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from packages.shared.python.models import RouterIntent


# Test cases: (query, expected_intent)
TEST_CASES: list[tuple[str, RouterIntent]] = [
    # Analytics queries (Text-to-SQL)
    ("Who spoke most?", RouterIntent.ANALYTICS_DB),
    ("How many messages were sent last week?", RouterIntent.ANALYTICS_DB),
    ("What's the most active channel?", RouterIntent.ANALYTICS_DB),
    ("Show me message counts by user", RouterIntent.ANALYTICS_DB),
    ("Which users are most active between 9am and 5pm?", RouterIntent.ANALYTICS_DB),
    
    # Semantic/RAG queries (Vector search)
    ("What are the main complaints?", RouterIntent.VECTOR_RAG),
    ("Summarize the discussion about the new feature", RouterIntent.VECTOR_RAG),
    ("What has been said about performance issues?", RouterIntent.VECTOR_RAG),
    ("Find messages where people discussed deployment", RouterIntent.VECTOR_RAG),
    
    # Web search queries (External information)
    ("What is the latest news about Python 3.13?", RouterIntent.WEB_SEARCH),
    ("How do I configure nginx for websockets?", RouterIntent.WEB_SEARCH),
    ("What's the current price of Bitcoin?", RouterIntent.WEB_SEARCH),
]


async def test_router_classification() -> tuple[int, int, list[str]]:
    """
    Test that the Router Agent correctly classifies query intents.
    
    Returns:
        Tuple of (passed_count, total_count, failure_messages)
    """
    try:
        from apps.api.src.agents.router import classify_intent
    except ImportError as e:
        print(f"IMPORT ERROR: {e}")
        print("Router Agent not implemented yet. This is expected in RED PHASE.")
        return (0, len(TEST_CASES), [f"ImportError: {e}"])
    
    passed = 0
    failures: list[str] = []
    
    for query, expected_intent in TEST_CASES:
        try:
            result = await classify_intent(query)
            
            if result == expected_intent:
                passed += 1
                print(f"✓ PASS: '{query[:40]}...' → {result.value}")
            else:
                msg = f"✗ FAIL: '{query[:40]}...' expected {expected_intent.value}, got {result.value}"
                print(msg)
                failures.append(msg)
        except Exception as e:
            msg = f"✗ ERROR: '{query[:40]}...' raised {type(e).__name__}: {e}"
            print(msg)
            failures.append(msg)
    
    return (passed, len(TEST_CASES), failures)


async def main() -> int:
    """Run the routing test suite."""
    print("=" * 60)
    print("Router Agent Intent Classification Test")
    print("=" * 60)
    print()
    
    passed, total, failures = await test_router_classification()
    
    print()
    print("=" * 60)
    print(f"Results: {passed}/{total} passed")
    print("=" * 60)
    
    if passed == total:
        print("✓ ALL TESTS PASSED - GREEN PHASE COMPLETE")
        return 0
    else:
        print("✗ TESTS FAILED - Expected in RED PHASE")
        print()
        print("Failures:")
        for f in failures:
            print(f"  {f}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
