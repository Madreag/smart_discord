"""
Leaky Bucket rate limiter for controlled throughput.

Use for bulk operations like message backfill or reactions.
Provides smooth rate limiting to avoid bursts that trigger Discord limits.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable, Any, TypeVar, Coroutine

import discord


T = TypeVar('T')


@dataclass
class LeakyBucket:
    """
    Leaky bucket rate limiter.
    
    Allows N requests per second with smoothing.
    Tokens refill at a constant rate.
    """
    
    rate: float  # Requests per second
    capacity: int  # Max burst size
    _tokens: float = field(default=0, init=False)
    _last_update: float = field(default=0, init=False)
    _lock: asyncio.Lock = field(default=None, init=False)
    
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
    
    @property
    def available_tokens(self) -> float:
        """Get current available tokens without acquiring."""
        now = time.monotonic()
        elapsed = now - self._last_update
        return min(self.capacity, self._tokens + elapsed * self.rate)


# Pre-configured buckets for common Discord operations
message_bucket = LeakyBucket(rate=4.5, capacity=5)  # ~5 messages per 5 seconds
reaction_bucket = LeakyBucket(rate=3.5, capacity=4)  # ~4 reactions per second
bulk_delete_bucket = LeakyBucket(rate=0.9, capacity=1)  # ~1 per second
edit_bucket = LeakyBucket(rate=4.5, capacity=5)  # ~5 edits per 5 seconds


async def send_message_rate_limited(
    channel: discord.TextChannel,
    content: str = None,
    **kwargs,
) -> discord.Message:
    """Send message with rate limiting."""
    await message_bucket.acquire()
    return await channel.send(content, **kwargs)


async def add_reaction_rate_limited(
    message: discord.Message,
    emoji: str,
) -> None:
    """Add reaction with rate limiting."""
    await reaction_bucket.acquire()
    await message.add_reaction(emoji)


async def edit_message_rate_limited(
    message: discord.Message,
    content: str = None,
    **kwargs,
) -> discord.Message:
    """Edit message with rate limiting."""
    await edit_bucket.acquire()
    return await message.edit(content=content, **kwargs)


async def bulk_operation(
    items: list[T],
    operation: Callable[[T], Coroutine[Any, Any, Any]],
    bucket: LeakyBucket,
) -> list[Any]:
    """
    Process items with rate limiting.
    
    Args:
        items: Items to process
        operation: Async function to call for each item
        bucket: LeakyBucket to use
        
    Returns:
        List of results from each operation
    """
    results = []
    for item in items:
        await bucket.acquire()
        result = await operation(item)
        results.append(result)
    return results


async def bulk_send_messages(
    channel: discord.TextChannel,
    messages: list[str],
) -> list[discord.Message]:
    """Send multiple messages with rate limiting."""
    return await bulk_operation(
        messages,
        lambda content: channel.send(content),
        message_bucket,
    )


async def bulk_delete_messages(
    messages: list[discord.Message],
) -> None:
    """Delete multiple messages with rate limiting."""
    await bulk_operation(
        messages,
        lambda msg: msg.delete(),
        bulk_delete_bucket,
    )
