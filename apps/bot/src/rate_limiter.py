"""
Discord Rate Limit Manager

Pre-emptively avoids rate limits by tracking headers.
Implements bucket-based rate limiting for controlled request flow.

Reference: https://discord.com/developers/docs/topics/rate-limits
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


class RateLimitManager:
    """
    Manages Discord API rate limits.
    
    Features:
    - Pre-emptive rate limit avoidance
    - Per-route bucket tracking
    - Global rate limit handling
    - Automatic retry on 429
    """
    
    def __init__(self):
        self.buckets: dict[str, RateLimitBucket] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._global_lock = asyncio.Lock()
        self._global_reset_at: float = 0.0
        self._stats = {
            "requests": 0,
            "rate_limited": 0,
            "pre_emptive_waits": 0,
        }
    
    def _get_route_key(self, method: str, path: str, guild_id: Optional[int] = None) -> str:
        """
        Generate a unique key for rate limit tracking.
        
        Discord buckets are per-route AND sometimes per-resource.
        """
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
        self._stats["requests"] += 1
        
        # Check global rate limit first
        async with self._global_lock:
            if self._global_reset_at > time.time():
                wait_time = self._global_reset_at - time.time()
                print(f"[RATELIMIT] Global limit hit, waiting {wait_time:.2f}s")
                self._stats["pre_emptive_waits"] += 1
                await asyncio.sleep(wait_time + 0.1)
        
        # Check route-specific limit
        async with self._locks[route_key]:
            bucket = self.buckets.get(route_key, RateLimitBucket())
            
            # Wait if we're low on remaining requests
            if bucket.remaining < min_remaining and bucket.reset_at > time.time():
                wait_time = bucket.reset_at - time.time()
                print(f"[RATELIMIT] {route_key}: waiting {wait_time:.2f}s ({bucket.remaining} remaining)")
                self._stats["pre_emptive_waits"] += 1
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
        
        # Update from headers (case-insensitive)
        headers_lower = {k.lower(): v for k, v in headers.items()}
        
        if "x-ratelimit-limit" in headers_lower:
            bucket.limit = int(headers_lower["x-ratelimit-limit"])
        
        if "x-ratelimit-remaining" in headers_lower:
            bucket.remaining = int(headers_lower["x-ratelimit-remaining"])
        
        if "x-ratelimit-reset" in headers_lower:
            bucket.reset_at = float(headers_lower["x-ratelimit-reset"])
        
        if "x-ratelimit-bucket" in headers_lower:
            bucket.bucket_id = headers_lower["x-ratelimit-bucket"]
        
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
        self._stats["rate_limited"] += 1
        
        headers_lower = {k.lower(): v for k, v in headers.items()}
        
        # Get retry-after from headers
        retry_after = float(headers_lower.get("retry-after", 5))
        is_global = headers_lower.get("x-ratelimit-global", "false").lower() == "true"
        
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
    
    def get_stats(self) -> dict:
        """Get rate limiting statistics."""
        return {
            **self._stats,
            "buckets_tracked": len(self.buckets),
        }
    
    def reset_stats(self) -> None:
        """Reset statistics counters."""
        self._stats = {
            "requests": 0,
            "rate_limited": 0,
            "pre_emptive_waits": 0,
        }


# Global instance
rate_limiter = RateLimitManager()
