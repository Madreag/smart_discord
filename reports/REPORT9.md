# REPORT 9: Rate Limiting & Discord API Best Practices

> **Priority**: P3 (Lower)  
> **Effort**: 3-4 hours  
> **Status**: Not Implemented

---

## 1. Executive Summary

Discord's API has strict rate limits. Without proper handling, the bot can get temporarily banned (429 errors) or permanently rate limited. This report covers:

1. Understanding Discord rate limits
2. Pre-emptive rate limit avoidance
3. Leaky bucket implementation
4. Retry strategies with backoff

---

## 2. Discord Rate Limit System

### How It Works

Discord uses a **bucket-based** rate limit system:

| Scope | Limit | Reset |
|-------|-------|-------|
| Global | 50 req/sec | Rolling |
| Per-Route | Varies | Per header |
| Per-Guild | Varies | Per header |

### Response Headers

```
X-RateLimit-Limit: 5           # Max requests in window
X-RateLimit-Remaining: 4       # Requests left
X-RateLimit-Reset: 1234567890  # Unix timestamp of reset
X-RateLimit-Bucket: abc123     # Bucket identifier
Retry-After: 5                 # Seconds to wait (on 429)
```

### Common Rate Limited Operations

| Operation | Typical Limit |
|-----------|---------------|
| Send Message | 5/5s per channel |
| Edit Message | 5/5s per channel |
| Delete Message | 5/1s per channel |
| Bulk Delete | 1/1s per channel |
| Create Reaction | 1/0.25s per channel |
| Get Guild | 1/1s |

---

## 3. Implementation Guide

### Rate Limit Manager

```python
# apps/bot/src/rate_limiter.py
"""
Discord Rate Limit Manager

Pre-emptively avoids rate limits by tracking headers.
Implements leaky bucket algorithm for controlled request flow.

Reference: https://support-dev.discord.com/hc/en-us/articles/6223003921559
"""

import asyncio
import time
from typing import Optional
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class RateLimitBucket:
    """Tracks rate limit state for a specific bucket."""
    limit: int = 50
    remaining: int = 50
    reset_at: float = 0.0
    bucket_id: Optional[str] = None


@dataclass
class RateLimitManager:
    """
    Manages Discord API rate limits.
    
    Features:
    - Pre-emptive rate limit avoidance
    - Per-route bucket tracking
    - Global rate limit handling
    - Automatic retry on 429
    """
    
    buckets: dict[str, RateLimitBucket] = field(default_factory=dict)
    _locks: dict[str, asyncio.Lock] = field(default_factory=lambda: defaultdict(asyncio.Lock))
    _global_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _global_reset_at: float = 0.0
    
    def _get_route_key(self, method: str, path: str, guild_id: Optional[int] = None) -> str:
        """
        Generate a unique key for rate limit tracking.
        
        Discord buckets are per-route AND sometimes per-resource.
        """
        # Major parameters that affect bucketing
        major_params = []
        
        if guild_id:
            major_params.append(f"guild:{guild_id}")
        
        # Extract channel_id from path if present
        if "/channels/" in path:
            parts = path.split("/channels/")
            if len(parts) > 1:
                channel_id = parts[1].split("/")[0]
                major_params.append(f"channel:{channel_id}")
        
        base = f"{method}:{path}"
        if major_params:
            return f"{base}:{':'.join(major_params)}"
        return base
    
    async def acquire(
        self,
        method: str,
        path: str,
        guild_id: Optional[int] = None,
        min_remaining: int = 2,
    ) -> None:
        """
        Acquire permission to make a request.
        
        Waits if we're close to the rate limit.
        
        Args:
            method: HTTP method
            path: API path
            guild_id: Optional guild ID for bucketing
            min_remaining: Minimum remaining requests before waiting
        """
        route_key = self._get_route_key(method, path, guild_id)
        
        # Check global rate limit first
        async with self._global_lock:
            if self._global_reset_at > time.time():
                wait_time = self._global_reset_at - time.time()
                print(f"[RATELIMIT] Global limit hit, waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time + 0.1)
        
        # Check route-specific limit
        async with self._locks[route_key]:
            bucket = self.buckets.get(route_key, RateLimitBucket())
            
            # Wait if we're low on remaining requests
            if bucket.remaining < min_remaining and bucket.reset_at > time.time():
                wait_time = bucket.reset_at - time.time()
                print(f"[RATELIMIT] {route_key}: waiting {wait_time:.2f}s ({bucket.remaining} remaining)")
                await asyncio.sleep(wait_time + 0.1)
                # Reset after waiting
                bucket.remaining = bucket.limit
            
            # Decrement remaining
            bucket.remaining = max(0, bucket.remaining - 1)
            self.buckets[route_key] = bucket
    
    def update_from_headers(
        self,
        method: str,
        path: str,
        headers: dict,
        guild_id: Optional[int] = None,
    ) -> None:
        """
        Update bucket state from response headers.
        
        Call this after every API response.
        """
        route_key = self._get_route_key(method, path, guild_id)
        
        bucket = self.buckets.get(route_key, RateLimitBucket())
        
        # Update from headers
        if "X-RateLimit-Limit" in headers:
            bucket.limit = int(headers["X-RateLimit-Limit"])
        
        if "X-RateLimit-Remaining" in headers:
            bucket.remaining = int(headers["X-RateLimit-Remaining"])
        
        if "X-RateLimit-Reset" in headers:
            bucket.reset_at = float(headers["X-RateLimit-Reset"])
        
        if "X-RateLimit-Bucket" in headers:
            bucket.bucket_id = headers["X-RateLimit-Bucket"]
        
        self.buckets[route_key] = bucket
    
    async def handle_429(
        self,
        method: str,
        path: str,
        headers: dict,
        guild_id: Optional[int] = None,
    ) -> float:
        """
        Handle a 429 rate limit response.
        
        Returns the number of seconds to wait.
        """
        route_key = self._get_route_key(method, path, guild_id)
        
        # Get retry-after from headers or body
        retry_after = float(headers.get("Retry-After", 5))
        is_global = headers.get("X-RateLimit-Global", "false").lower() == "true"
        
        if is_global:
            async with self._global_lock:
                self._global_reset_at = time.time() + retry_after
                print(f"[RATELIMIT] GLOBAL 429! Waiting {retry_after}s")
        else:
            bucket = self.buckets.get(route_key, RateLimitBucket())
            bucket.remaining = 0
            bucket.reset_at = time.time() + retry_after
            self.buckets[route_key] = bucket
            print(f"[RATELIMIT] 429 on {route_key}, waiting {retry_after}s")
        
        return retry_after


# Global instance
rate_limiter = RateLimitManager()
```

### Integration with HTTP Client

```python
# apps/bot/src/discord_client.py
"""
Rate-limited Discord HTTP client wrapper.
"""

import httpx
import asyncio
from typing import Optional, Any

from apps.bot.src.rate_limiter import rate_limiter


class RateLimitedClient:
    """HTTP client with automatic rate limit handling."""
    
    def __init__(self, token: str):
        self.token = token
        self.base_url = "https://discord.com/api/v10"
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bot {token}"},
            timeout=30.0,
        )
    
    async def request(
        self,
        method: str,
        path: str,
        guild_id: Optional[int] = None,
        max_retries: int = 3,
        **kwargs,
    ) -> httpx.Response:
        """
        Make a rate-limited request to Discord API.
        
        Automatically:
        - Waits before hitting rate limit
        - Retries on 429 with backoff
        - Updates bucket state from headers
        """
        url = f"{self.base_url}{path}"
        
        for attempt in range(max_retries + 1):
            # Pre-emptive rate limit check
            await rate_limiter.acquire(method, path, guild_id)
            
            # Make request
            response = await self._client.request(method, url, **kwargs)
            
            # Update rate limit state
            rate_limiter.update_from_headers(method, path, dict(response.headers), guild_id)
            
            # Handle 429
            if response.status_code == 429:
                if attempt < max_retries:
                    retry_after = await rate_limiter.handle_429(
                        method, path, dict(response.headers), guild_id
                    )
                    await asyncio.sleep(retry_after + 0.5)
                    continue
                else:
                    raise Exception(f"Rate limited after {max_retries} retries")
            
            return response
        
        raise Exception("Max retries exceeded")
    
    async def get(self, path: str, **kwargs) -> httpx.Response:
        return await self.request("GET", path, **kwargs)
    
    async def post(self, path: str, **kwargs) -> httpx.Response:
        return await self.request("POST", path, **kwargs)
    
    async def patch(self, path: str, **kwargs) -> httpx.Response:
        return await self.request("PATCH", path, **kwargs)
    
    async def delete(self, path: str, **kwargs) -> httpx.Response:
        return await self.request("DELETE", path, **kwargs)
```

### Discord.py Integration

```python
# apps/bot/src/bot.py (add rate limit handling)

from discord.ext import commands
import discord

# Custom HTTPClient with rate limit awareness
class RateLimitAwareBot(commands.Bot):
    """Bot with enhanced rate limit handling."""
    
    async def on_error(self, event_method: str, *args, **kwargs):
        """Handle errors including rate limits."""
        import sys
        exc = sys.exc_info()[1]
        
        if isinstance(exc, discord.HTTPException):
            if exc.status == 429:
                # Rate limited - log and let discord.py handle retry
                print(f"[RATELIMIT] Rate limited in {event_method}")
                return
        
        # Re-raise other errors
        raise


# Use as:
bot = RateLimitAwareBot(command_prefix="/", intents=intents)
```

---

## 4. Leaky Bucket for Bulk Operations

```python
# apps/bot/src/leaky_bucket.py
"""
Leaky Bucket rate limiter for controlled throughput.

Use for bulk operations like message backfill.
"""

import asyncio
import time
from dataclasses import dataclass


@dataclass
class LeakyBucket:
    """
    Leaky bucket rate limiter.
    
    Allows N requests per second with smoothing.
    """
    
    rate: float  # Requests per second
    capacity: int  # Max burst size
    _tokens: float = 0
    _last_update: float = 0
    _lock: asyncio.Lock = None
    
    def __post_init__(self):
        self._tokens = float(self.capacity)
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def acquire(self, tokens: int = 1) -> None:
        """
        Acquire tokens, waiting if necessary.
        
        Args:
            tokens: Number of tokens to acquire
        """
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last_update
                self._last_update = now
                
                # Refill tokens based on elapsed time
                self._tokens = min(
                    self.capacity,
                    self._tokens + elapsed * self.rate
                )
                
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                
                # Calculate wait time
                needed = tokens - self._tokens
                wait_time = needed / self.rate
                await asyncio.sleep(wait_time)


# Pre-configured buckets for common operations
message_bucket = LeakyBucket(rate=4.5, capacity=5)  # ~5 messages per second
reaction_bucket = LeakyBucket(rate=3.5, capacity=4)  # ~4 reactions per second
bulk_delete_bucket = LeakyBucket(rate=0.9, capacity=1)  # ~1 per second


async def send_message_rate_limited(channel, content: str, **kwargs):
    """Send message with rate limiting."""
    await message_bucket.acquire()
    return await channel.send(content, **kwargs)


async def bulk_operation(items: list, operation, bucket: LeakyBucket):
    """
    Process items with rate limiting.
    
    Args:
        items: Items to process
        operation: Async function to call for each item
        bucket: LeakyBucket to use
    """
    results = []
    for item in items:
        await bucket.acquire()
        result = await operation(item)
        results.append(result)
    return results
```

---

## 5. Best Practices Summary

1. **Always check headers** - Update rate limit state after every request
2. **Pre-emptive waiting** - Don't wait for 429, predict and wait before
3. **Use leaky bucket** - For bulk operations, smooth out request rate
4. **Handle global limits** - They affect all routes simultaneously
5. **Log rate limits** - Track patterns to optimize batch sizes
6. **Exponential backoff** - On 429, wait longer each retry

---

## 6. References

- [Discord Rate Limits](https://discord.com/developers/docs/topics/rate-limits)
- [Discord Developer Support](https://support-dev.discord.com/hc/en-us/articles/6223003921559)
- [Leaky Bucket Algorithm](https://en.wikipedia.org/wiki/Leaky_bucket)

---

## 7. Checklist

- [ ] Create `apps/bot/src/rate_limiter.py`
- [ ] Create `apps/bot/src/leaky_bucket.py`
- [ ] Integrate with Discord HTTP requests
- [ ] Add logging for rate limit events
- [ ] Test with bulk message operations
- [ ] Monitor 429 error frequency
