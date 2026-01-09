# REPORT 12: Additional Slash Commands (/ai summary, /ai search)

> **Priority**: P3 (Lower)  
> **Effort**: Low (3-4 hours)  
> **Status**: Not Implemented

---

## 1. Executive Summary

The bot currently has basic commands (`/ai question:`, `/stats`, `/index`), but lacks utility commands that users frequently need:

- `/ai summary` - Summarize recent channel activity
- `/ai search` - Search chat history with keywords
- `/ai topics` - Show trending topics

These commands improve user experience and showcase the bot's capabilities.

---

## 2. Current Commands

```python
# apps/bot/src/bot.py (existing)
@bot.tree.command(name="ai", description="Ask a question")
async def ai_ask(interaction, question: str, channels: Optional[str] = None):
    ...

@bot.tree.command(name="stats", description="Show server statistics")
async def stats(interaction):
    ...

@bot.tree.command(name="index", description="Toggle channel indexing")
async def index(interaction, channel: discord.TextChannel):
    ...
```

---

## 3. Implementation Guide

### Command Group Structure

Discord.py supports command groups for organizing related commands:

```python
# apps/bot/src/commands/__init__.py
"""
Slash Command Definitions

Organized using app_commands.Group for cleaner command structure.
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
from datetime import datetime, timedelta

import httpx


# API base URL
API_URL = "http://api:8000"  # Docker internal


class AICommands(app_commands.Group):
    """AI-powered commands for the Discord bot."""
    
    def __init__(self):
        super().__init__(name="ai", description="AI-powered commands")
    
    @app_commands.command(name="ask", description="Ask a question about this server's discussions")
    @app_commands.describe(
        question="Your question about the server's chat history",
        channels="Comma-separated channel names to search (optional)",
    )
    async def ask(
        self,
        interaction: discord.Interaction,
        question: str,
        channels: Optional[str] = None,
    ):
        """Ask a question using RAG."""
        await interaction.response.defer(thinking=True)
        
        # Parse channel filter
        channel_ids = None
        if channels:
            channel_names = [c.strip().lstrip("#") for c in channels.split(",")]
            channel_ids = [
                ch.id for ch in interaction.guild.text_channels
                if ch.name in channel_names
            ]
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{API_URL}/ask",
                    json={
                        "query": question,
                        "guild_id": interaction.guild.id,
                        "channel_ids": channel_ids,
                    },
                )
                data = response.json()
            
            # Build embed
            embed = discord.Embed(
                title="🤖 AI Response",
                description=data.get("answer", "No answer available"),
                color=discord.Color.blurple(),
            )
            
            # Add sources if available
            sources = data.get("sources", [])
            if sources:
                source_text = "\n".join([f"• {s['preview'][:100]}..." for s in sources[:3]])
                embed.add_field(name="📚 Sources", value=source_text, inline=False)
            
            embed.set_footer(text=f"Routed to: {data.get('routed_to', 'unknown')}")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            await interaction.followup.send(
                f"❌ Error processing your question: {str(e)[:100]}",
                ephemeral=True,
            )
    
    @app_commands.command(name="summary", description="Summarize recent channel activity")
    @app_commands.describe(
        channel="Channel to summarize (default: current)",
        hours="Hours to look back (default: 24, max: 168)",
    )
    async def summary(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        hours: int = 24,
    ):
        """Generate a summary of recent channel activity."""
        await interaction.response.defer(thinking=True)
        
        # Validate hours
        hours = min(max(hours, 1), 168)  # 1 hour to 1 week
        
        target_channel = channel or interaction.channel
        
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(
                    f"{API_URL}/summary",
                    json={
                        "guild_id": interaction.guild.id,
                        "channel_id": target_channel.id,
                        "hours": hours,
                    },
                )
                data = response.json()
            
            if data.get("status") == "no_messages":
                await interaction.followup.send(
                    f"📭 No messages found in #{target_channel.name} in the last {hours} hours.",
                    ephemeral=True,
                )
                return
            
            embed = discord.Embed(
                title=f"📋 Summary: #{target_channel.name}",
                description=data.get("summary", "No summary available"),
                color=discord.Color.green(),
                timestamp=datetime.utcnow(),
            )
            
            # Add metadata
            embed.add_field(
                name="📊 Stats",
                value=f"**Messages**: {data.get('message_count', 0)}\n"
                      f"**Participants**: {data.get('participant_count', 0)}\n"
                      f"**Time Range**: Last {hours}h",
                inline=True,
            )
            
            # Add key topics if available
            topics = data.get("topics", [])
            if topics:
                embed.add_field(
                    name="🏷️ Key Topics",
                    value=", ".join(topics[:5]),
                    inline=True,
                )
            
            embed.set_footer(text=f"Requested by {interaction.user.display_name}")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            await interaction.followup.send(
                f"❌ Error generating summary: {str(e)[:100]}",
                ephemeral=True,
            )
    
    @app_commands.command(name="search", description="Search chat history")
    @app_commands.describe(
        query="Search terms or keywords",
        channel="Limit search to specific channel (optional)",
        user="Filter by user (optional)",
        limit="Max results (default: 5, max: 10)",
    )
    async def search(
        self,
        interaction: discord.Interaction,
        query: str,
        channel: Optional[discord.TextChannel] = None,
        user: Optional[discord.Member] = None,
        limit: int = 5,
    ):
        """Search chat history using semantic search."""
        await interaction.response.defer(thinking=True)
        
        limit = min(max(limit, 1), 10)
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{API_URL}/search",
                    json={
                        "query": query,
                        "guild_id": interaction.guild.id,
                        "channel_id": channel.id if channel else None,
                        "user_id": user.id if user else None,
                        "limit": limit,
                    },
                )
                data = response.json()
            
            results = data.get("results", [])
            
            if not results:
                await interaction.followup.send(
                    f"🔍 No results found for: **{query}**",
                    ephemeral=True,
                )
                return
            
            embed = discord.Embed(
                title=f"🔍 Search Results: {query}",
                color=discord.Color.blue(),
            )
            
            for i, result in enumerate(results[:limit], 1):
                # Truncate content for display
                content = result.get("content", "")[:200]
                if len(result.get("content", "")) > 200:
                    content += "..."
                
                author = result.get("author", "Unknown")
                timestamp = result.get("timestamp", "")
                channel_name = result.get("channel", "Unknown")
                score = result.get("score", 0)
                
                embed.add_field(
                    name=f"{i}. {author} in #{channel_name}",
                    value=f"{content}\n*Relevance: {score:.0%}*",
                    inline=False,
                )
            
            embed.set_footer(text=f"Found {len(results)} results")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            await interaction.followup.send(
                f"❌ Error searching: {str(e)[:100]}",
                ephemeral=True,
            )
    
    @app_commands.command(name="topics", description="Show trending topics in the server")
    @app_commands.describe(
        days="Days to analyze (default: 7, max: 30)",
    )
    async def topics(
        self,
        interaction: discord.Interaction,
        days: int = 7,
    ):
        """Show trending topics using keyword extraction."""
        await interaction.response.defer(thinking=True)
        
        days = min(max(days, 1), 30)
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(
                    f"{API_URL}/guilds/{interaction.guild.id}/topics",
                    params={"days": days},
                )
                data = response.json()
            
            topics = data.get("topics", [])
            
            if not topics:
                await interaction.followup.send(
                    "🏷️ No trending topics found. Try increasing the time range.",
                    ephemeral=True,
                )
                return
            
            embed = discord.Embed(
                title=f"🏷️ Trending Topics (Last {days} days)",
                color=discord.Color.purple(),
            )
            
            # Format topics
            topic_lines = []
            for i, topic in enumerate(topics[:10], 1):
                name = topic.get("name", "Unknown")
                count = topic.get("count", 0)
                trend = topic.get("trend", "stable")
                
                trend_emoji = "📈" if trend == "up" else "📉" if trend == "down" else "➡️"
                topic_lines.append(f"{i}. **{name}** ({count} mentions) {trend_emoji}")
            
            embed.description = "\n".join(topic_lines)
            embed.set_footer(text=f"Analyzed {data.get('message_count', 0)} messages")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            await interaction.followup.send(
                f"❌ Error fetching topics: {str(e)[:100]}",
                ephemeral=True,
            )


# Register commands with bot
async def setup_commands(bot: commands.Bot):
    """Add command groups to the bot."""
    bot.tree.add_command(AICommands())
```

### API Endpoints

```python
# apps/api/src/main.py (add new endpoints)

from pydantic import BaseModel
from typing import Optional


class SummaryRequest(BaseModel):
    guild_id: int
    channel_id: int
    hours: int = 24


class SummaryResponse(BaseModel):
    status: str
    summary: str
    message_count: int
    participant_count: int
    topics: list[str]


@app.post("/summary", response_model=SummaryResponse)
async def generate_summary(request: SummaryRequest) -> SummaryResponse:
    """
    Generate a summary of recent channel activity.
    """
    from datetime import datetime, timedelta
    from sqlalchemy import create_engine, text
    
    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    cutoff = datetime.utcnow() - timedelta(hours=request.hours)
    
    with engine.connect() as conn:
        # Fetch recent messages
        result = conn.execute(text("""
            SELECT m.content, u.username, m.message_timestamp
            FROM messages m
            JOIN users u ON m.author_id = u.id
            WHERE m.guild_id = :guild_id
              AND m.channel_id = :channel_id
              AND m.message_timestamp > :cutoff
              AND m.is_deleted = FALSE
              AND LENGTH(m.content) > 5
            ORDER BY m.message_timestamp ASC
            LIMIT 500
        """), {
            "guild_id": request.guild_id,
            "channel_id": request.channel_id,
            "cutoff": cutoff,
        })
        rows = result.fetchall()
    
    if not rows:
        return SummaryResponse(
            status="no_messages",
            summary="",
            message_count=0,
            participant_count=0,
            topics=[],
        )
    
    # Build conversation text
    messages_text = "\n".join([
        f"{row.username}: {row.content}"
        for row in rows
    ])
    
    # Count unique participants
    participants = set(row.username for row in rows)
    
    # Generate summary using LLM
    from openai import AsyncOpenAI
    
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "You are a helpful assistant that summarizes Discord conversations. "
                           "Provide a concise 2-3 paragraph summary highlighting main topics discussed, "
                           "any decisions made, and notable interactions. Also extract 3-5 key topics as keywords."
            },
            {
                "role": "user",
                "content": f"Summarize this conversation:\n\n{messages_text[:8000]}"
            },
        ],
        max_tokens=500,
        temperature=0.3,
    )
    
    summary = response.choices[0].message.content
    
    # Extract topics (simple keyword extraction)
    topics = extract_topics(messages_text)
    
    return SummaryResponse(
        status="success",
        summary=summary,
        message_count=len(rows),
        participant_count=len(participants),
        topics=topics,
    )


class SearchRequest(BaseModel):
    query: str
    guild_id: int
    channel_id: Optional[int] = None
    user_id: Optional[int] = None
    limit: int = 5


class SearchResult(BaseModel):
    content: str
    author: str
    channel: str
    timestamp: str
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResult]


@app.post("/search", response_model=SearchResponse)
async def search_messages(request: SearchRequest) -> SearchResponse:
    """
    Semantic search across chat history.
    """
    from apps.api.src.services.embedding_service import generate_embedding
    from apps.api.src.services.qdrant_service import qdrant_service
    
    # Generate query embedding
    query_embedding = generate_embedding(request.query)
    
    # Search Qdrant
    results = await qdrant_service.search(
        query_embedding=query_embedding,
        guild_id=request.guild_id,
        channel_ids=[request.channel_id] if request.channel_id else None,
        limit=request.limit,
    )
    
    # Fetch message details from Postgres
    from sqlalchemy import create_engine, text
    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    
    search_results = []
    for r in results:
        payload = r.get("payload", {})
        message_ids = payload.get("message_ids", [])
        
        if not message_ids:
            continue
        
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT m.content, u.username, c.name as channel_name, m.message_timestamp
                FROM messages m
                JOIN users u ON m.author_id = u.id
                JOIN channels c ON m.channel_id = c.id
                WHERE m.id = :msg_id
            """), {"msg_id": message_ids[0]})
            row = result.fetchone()
        
        if row:
            search_results.append(SearchResult(
                content=row.content,
                author=row.username,
                channel=row.channel_name,
                timestamp=row.message_timestamp.isoformat(),
                score=r.get("score", 0),
            ))
    
    return SearchResponse(results=search_results)


@app.get("/guilds/{guild_id}/topics")
async def get_trending_topics(guild_id: int, days: int = 7) -> dict:
    """
    Extract trending topics from recent messages.
    """
    from datetime import datetime, timedelta
    from collections import Counter
    import re
    
    from sqlalchemy import create_engine, text
    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT content FROM messages
            WHERE guild_id = :guild_id
              AND message_timestamp > :cutoff
              AND is_deleted = FALSE
              AND LENGTH(content) > 10
        """), {"guild_id": guild_id, "cutoff": cutoff})
        rows = result.fetchall()
    
    if not rows:
        return {"topics": [], "message_count": 0}
    
    # Simple keyword extraction
    all_text = " ".join(row.content for row in rows)
    words = re.findall(r'\b[a-zA-Z]{4,15}\b', all_text.lower())
    
    # Remove common stop words
    stop_words = {
        "that", "this", "with", "have", "just", "like", "from", "they",
        "would", "there", "their", "what", "about", "which", "when",
        "make", "been", "more", "some", "could", "than", "other",
    }
    words = [w for w in words if w not in stop_words]
    
    # Count frequencies
    word_counts = Counter(words)
    top_topics = word_counts.most_common(10)
    
    return {
        "guild_id": guild_id,
        "days": days,
        "message_count": len(rows),
        "topics": [
            {"name": word, "count": count, "trend": "stable"}
            for word, count in top_topics
        ],
    }


def extract_topics(text: str, n: int = 5) -> list[str]:
    """Simple topic extraction from text."""
    from collections import Counter
    import re
    
    words = re.findall(r'\b[a-zA-Z]{4,15}\b', text.lower())
    stop_words = {"that", "this", "with", "have", "just", "like", "from", "they", "would"}
    words = [w for w in words if w not in stop_words]
    
    return [word for word, _ in Counter(words).most_common(n)]
```

### Register Commands in Bot

```python
# apps/bot/src/bot.py (update setup)

from apps.bot.src.commands import setup_commands

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    
    # Register command groups
    await setup_commands(bot)
    
    # Sync commands with Discord
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
```

---

## 4. Command Reference

| Command | Description | Example |
|---------|-------------|---------|
| `/ai ask` | Ask questions about chat history | `/ai ask question: What was discussed about the update?` |
| `/ai summary` | Summarize recent activity | `/ai summary channel: #general hours: 12` |
| `/ai search` | Search messages semantically | `/ai search query: bug report user: @dev` |
| `/ai topics` | Show trending topics | `/ai topics days: 14` |

---

## 5. Rate Limiting Commands

Add cooldowns to prevent abuse:

```python
from discord.app_commands import checks, Cooldown

class AICommands(app_commands.Group):
    
    @app_commands.command(name="summary")
    @app_commands.checks.cooldown(1, 60.0, key=lambda i: (i.guild_id, i.user.id))
    async def summary(self, interaction, ...):
        ...
    
    async def on_error(self, interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"⏰ Please wait {error.retry_after:.0f}s before using this command again.",
                ephemeral=True,
            )
        else:
            raise error
```

---

## 6. References

- [Discord.py Application Commands](https://discordpy.readthedocs.io/en/stable/interactions/api.html)
- [Discord Slash Commands Guide](https://discord.com/developers/docs/interactions/application-commands)
- [Command Groups](https://discordpy.readthedocs.io/en/stable/interactions/api.html#discord.app_commands.Group)

---

## 7. Checklist

- [ ] Create `apps/bot/src/commands/__init__.py` with `AICommands` group
- [ ] Implement `/ai summary` command
- [ ] Implement `/ai search` command
- [ ] Implement `/ai topics` command
- [ ] Add `/summary` API endpoint
- [ ] Add `/search` API endpoint
- [ ] Add `/guilds/{guild_id}/topics` API endpoint
- [ ] Add cooldowns to prevent abuse
- [ ] Register commands in bot setup
- [ ] Sync commands with Discord
- [ ] Test all commands in a real server
