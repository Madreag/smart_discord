#!/usr/bin/env python3
"""
Test Rate Limiting functionality.
"""

import sys
import asyncio
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).parent.parent))

from apps.bot.src.rate_limiter import RateLimitManager
from apps.bot.src.leaky_bucket import LeakyBucket


def test_rate_limit_manager():
    """Test the rate limit manager."""
    print("Testing RateLimitManager...")
    print("=" * 50)
    
    manager = RateLimitManager()
    
    # Test route key generation
    key1 = manager._get_route_key("POST", "/channels/123/messages", guild_id=456)
    key2 = manager._get_route_key("GET", "/guilds/456")
    
    print(f"Route key 1: {key1}")
    print(f"Route key 2: {key2}")
    
    assert "channel:123" in key1
    assert "guild:456" in key1
    print("✓ Route key generation works")
    
    # Test header parsing
    headers = {
        "X-RateLimit-Limit": "5",
        "X-RateLimit-Remaining": "3",
        "X-RateLimit-Reset": str(time.time() + 10),
        "X-RateLimit-Bucket": "abc123",
    }
    
    manager.update_from_headers("POST", "/channels/123/messages", headers, guild_id=456)
    bucket = manager.buckets.get(key1)
    
    assert bucket is not None
    assert bucket.limit == 5
    assert bucket.remaining == 3
    print("✓ Header parsing works")
    
    # Test stats
    stats = manager.get_stats()
    print(f"Stats: {stats}")
    assert "requests" in stats
    print("✓ Stats tracking works")
    
    print()
    return True


async def test_leaky_bucket():
    """Test the leaky bucket rate limiter."""
    print("Testing LeakyBucket...")
    print("=" * 50)
    
    # Create a fast bucket for testing
    bucket = LeakyBucket(rate=10.0, capacity=3)  # 10 per second, burst of 3
    
    # Test burst capacity
    start = time.monotonic()
    for i in range(3):
        await bucket.acquire()
    elapsed = time.monotonic() - start
    
    print(f"Burst of 3: {elapsed:.3f}s")
    assert elapsed < 0.1, "Burst should be fast"
    print("✓ Burst capacity works")
    
    # Test rate limiting kicks in
    start = time.monotonic()
    await bucket.acquire()  # 4th request should wait
    elapsed = time.monotonic() - start
    
    print(f"4th request: {elapsed:.3f}s")
    assert elapsed > 0.05, "Should have waited for token refill"
    print("✓ Rate limiting works")
    
    # Test available tokens
    tokens = bucket.available_tokens
    print(f"Available tokens: {tokens:.2f}")
    print("✓ Token tracking works")
    
    print()
    return True


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("RATE LIMITING TESTS")
    print("=" * 60 + "\n")
    
    test1 = test_rate_limit_manager()
    test2 = await test_leaky_bucket()
    
    print("=" * 60)
    if test1 and test2:
        print("✓ All rate limiting tests passed!")
    else:
        print("✗ Some tests failed")
    print("=" * 60)
    
    return test1 and test2


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
