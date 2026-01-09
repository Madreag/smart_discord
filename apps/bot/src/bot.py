"""
Discord Bot - Ingestion Layer

Listens to Discord Gateway events and pushes tasks to Redis/Celery.
NEVER processes AI logic locally to keep event loop unblocked.

CRITICAL PATTERNS:
1. Deferral Pattern: Always defer /ai commands with thinking=True
2. Hybrid Storage: Store in Postgres before pushing to Qdrant
3. Right to be Forgotten: Handle on_message_delete properly
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import httpx
from sqlalchemy import create_engine, text

from apps.bot.src.config import get_bot_settings
from packages.shared.python.models import IndexTaskPayload, DeleteTaskPayload


# Database connection for direct message saving (bypasses Celery)
_db_engine = None

def get_db_engine():
    """Get or create database engine."""
    global _db_engine
    if _db_engine is None:
        settings = get_bot_settings()
        sync_url = settings.database_url.replace("+asyncpg", "")
        _db_engine = create_engine(sync_url, pool_pre_ping=True)
    return _db_engine


def save_message_to_db(message: "discord.Message") -> bool:
    """
    Save a Discord message directly to PostgreSQL.
    
    Returns True if successful, False otherwise.
    """
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            # Upsert user first
            conn.execute(text("""
                INSERT INTO users (id, username, global_name, first_seen_at, updated_at)
                VALUES (:id, :username, :global_name, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    username = EXCLUDED.username,
                    global_name = EXCLUDED.global_name,
                    updated_at = NOW()
            """), {
                "id": message.author.id,
                "username": message.author.name,
                "global_name": message.author.display_name,
            })
            
            # Upsert guild
            conn.execute(text("""
                INSERT INTO guilds (id, name, owner_id, joined_at, created_at, updated_at)
                VALUES (:id, :name, :owner_id, NOW(), NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    updated_at = NOW()
            """), {
                "id": message.guild.id,
                "name": message.guild.name,
                "owner_id": message.guild.owner_id,
            })
            
            # Upsert channel
            conn.execute(text("""
                INSERT INTO channels (id, guild_id, name, type, created_at, updated_at)
                VALUES (:id, :guild_id, :name, :type, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    updated_at = NOW()
            """), {
                "id": message.channel.id,
                "guild_id": message.guild.id,
                "name": message.channel.name,
                "type": getattr(message.channel, 'type', 0).value if hasattr(getattr(message.channel, 'type', 0), 'value') else 0,
            })
            
            # Insert message
            conn.execute(text("""
                INSERT INTO messages (id, channel_id, guild_id, author_id, content, reply_to_id, 
                                      attachment_count, embed_count, mention_count, message_timestamp, 
                                      created_at, updated_at)
                VALUES (:id, :channel_id, :guild_id, :author_id, :content, :reply_to_id,
                        :attachment_count, :embed_count, :mention_count, :message_timestamp,
                        NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
            """), {
                "id": message.id,
                "channel_id": message.channel.id,
                "guild_id": message.guild.id,
                "author_id": message.author.id,
                "content": message.content or "",
                "reply_to_id": message.reference.message_id if message.reference else None,
                "attachment_count": len(message.attachments),
                "embed_count": len(message.embeds),
                "mention_count": len(message.mentions),
                "message_timestamp": message.created_at,
            })
            
            conn.commit()
            return True
    except Exception as e:
        print(f"Error saving message to DB: {e}")
        return False


# Bot setup with required intents
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True  # Required to receive message events
intents.guilds = True
intents.members = True


class IntelligenceBot(commands.Bot):
    """Discord bot for community intelligence."""
    
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )
        self.settings = get_bot_settings()
    
    async def setup_hook(self) -> None:
        """Called when the bot is starting up."""
        # Sync slash commands
        await self.tree.sync()
        print(f"Synced {len(self.tree.get_commands())} commands")
    
    async def on_ready(self) -> None:
        """Called when the bot is fully connected."""
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print(f"Connected to {len(self.guilds)} guilds")


bot = IntelligenceBot()


# =============================================================================
# MESSAGE EVENTS (Ingestion)
# =============================================================================

@bot.listen('on_message')
async def on_message_handler(message: discord.Message) -> None:
    """
    Handle incoming messages.
    
    Stores message directly in Postgres (bypasses Celery for local dev).
    Also responds to @mentions.
    """
    try:
        # Debug: Log all messages received
        print(f"[DEBUG] Message received from {message.author}: {message.content[:50] if message.content else '(empty)'}...")
        
        # Ignore bot messages
        if message.author.bot:
            return
        
        # Ignore DMs
        if not message.guild:
            return
        
        # Save directly to PostgreSQL (bypasses Celery/Redis)
        save_message_to_db(message)
        
        # Check if bot was mentioned (user mention or role mention with bot's name)
        bot_mentioned = (
            bot.user in message.mentions or 
            f'<@{bot.user.id}>' in message.content or
            f'<@!{bot.user.id}>' in message.content
        )
        
        # Also check for role mentions that match bot's name (e.g. @smart_bot role)
        if not bot_mentioned and message.role_mentions:
            bot_name_lower = bot.user.name.lower()
            for role in message.role_mentions:
                if role.name.lower() == bot_name_lower or 'smart' in role.name.lower():
                    bot_mentioned = True
                    break
        
        if bot_mentioned:
            print(f"Bot mentioned by {message.author}: {message.content}")
            await handle_mention(message)
            
    except Exception as e:
        print(f"[ERROR] on_message error: {e}")


async def handle_mention(message: discord.Message) -> None:
    """
    Handle @mention of the bot - respond to the question in the message.
    """
    # Remove the bot mention from the message to get the question
    question = message.content
    for mention in message.mentions:
        question = question.replace(f'<@{mention.id}>', '').replace(f'<@!{mention.id}>', '')
    question = question.strip()
    
    if not question:
        await message.reply("Hey! Ask me anything by mentioning me with a question. For example: `@bot What is Python?`")
        return
    
    # Show typing indicator while processing
    async with message.channel.typing():
        try:
            # Call API directly
            async with httpx.AsyncClient() as client:
                api_response = await client.post(
                    "http://localhost:8000/ask",
                    json={
                        "guild_id": message.guild.id,
                        "query": question,
                    },
                    timeout=60.0,
                )
                api_response.raise_for_status()
                response = api_response.json()
            
            answer = response.get("answer", "Sorry, I couldn't process that question.")
            routed_to = response.get("routed_to", "unknown")
            
            # Build embed for nicer formatting
            embed = discord.Embed(
                description=answer[:4000],
                color=discord.Color.blue(),
            )
            embed.set_footer(text=f"Routed: {routed_to}")
            
            await message.reply(embed=embed)
            
        except Exception as e:
            await message.reply(f"Sorry, I encountered an error: {str(e)}")


@bot.event
async def on_message_delete(message: discord.Message) -> None:
    """
    Handle message deletion (Right to be Forgotten).
    
    CONSTRAINT: Soft delete in Postgres, hard delete in Qdrant.
    """
    if not message.guild:
        return
    
    # TODO: Get qdrant_point_id from Postgres
    # For now, we'll use a placeholder
    qdrant_point_id = None
    
    if qdrant_point_id:
        payload = DeleteTaskPayload(
            guild_id=message.guild.id,
            message_id=message.id,
            qdrant_point_id=qdrant_point_id,
        )
        
        # Queue deletion task
        delete_message_vector.delay(payload.model_dump())


@bot.event
async def on_bulk_message_delete(messages: list[discord.Message]) -> None:
    """Handle bulk message deletion."""
    for message in messages:
        await on_message_delete(message)


# =============================================================================
# SLASH COMMANDS
# =============================================================================

@bot.tree.command(name="ai", description="Ask a question about this server's discussions")
@app_commands.describe(
    question="Your question about the server's chat history",
    channels="Comma-separated channel names to search (optional)",
)
async def ai_ask(
    interaction: discord.Interaction,
    question: str,
    channels: Optional[str] = None,
) -> None:
    """
    /ai ask command - Query the community intelligence system.
    
    CRITICAL: Uses Deferral Pattern to prevent 3-second timeout.
    """
    # DEFERRAL PATTERN: Immediately defer with thinking indicator
    # This gives us 15 minutes instead of 3 seconds
    await interaction.response.defer(thinking=True)
    
    try:
        # Parse channel filter if provided
        channel_ids: Optional[list[int]] = None
        if channels:
            channel_names = [c.strip().lower() for c in channels.split(",")]
            channel_ids = [
                ch.id for ch in interaction.guild.channels
                if ch.name.lower() in channel_names
            ]
        
        # Call API directly (bypasses Celery/Redis for simpler local dev)
        async with httpx.AsyncClient() as client:
            api_response = await client.post(
                "http://localhost:8000/ask",
                json={
                    "guild_id": interaction.guild.id,
                    "query": question,
                    "channel_ids": channel_ids,
                },
                timeout=60.0,
            )
            api_response.raise_for_status()
            response = api_response.json()
        
        # Format response
        answer = response.get("answer", "Unable to process query")
        routed_to = response.get("routed_to", "unknown")
        execution_time = response.get("execution_time_ms", 0)
        
        # Build embed
        embed = discord.Embed(
            title="AI Response",
            description=answer[:4000],  # Discord embed limit
            color=discord.Color.blue(),
        )
        embed.set_footer(text=f"Routed: {routed_to} | Time: {execution_time:.0f}ms")
        
        # Add sources if available
        sources = response.get("sources", [])
        if sources:
            source_text = "\n".join([
                f"• <#{s['channel_id']}> (score: {s['relevance_score']:.2f})"
                for s in sources[:5]
            ])
            embed.add_field(name="Sources", value=source_text, inline=False)
        
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        await interaction.followup.send(
            f"Error processing your question: {str(e)}",
            ephemeral=True,
        )


@bot.tree.command(name="stats", description="Show server statistics")
async def stats(interaction: discord.Interaction) -> None:
    """Show basic server statistics."""
    await interaction.response.defer(thinking=True)
    
    try:
        # Quick stats query via direct API call
        async with httpx.AsyncClient() as client:
            api_response = await client.post(
                "http://localhost:8000/ask",
                json={
                    "guild_id": interaction.guild.id,
                    "query": "How many messages total and who are the top 5 most active users?",
                },
                timeout=30.0,
            )
            api_response.raise_for_status()
            response = api_response.json()
        
        embed = discord.Embed(
            title=f"📊 {interaction.guild.name} Statistics",
            description=response.get("answer", "Stats unavailable"),
            color=discord.Color.green(),
        )
        
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        await interaction.followup.send(
            f"Error fetching stats: {str(e)}",
            ephemeral=True,
        )


@bot.tree.command(name="index", description="Toggle indexing for a channel (Admin only)")
@app_commands.describe(channel="The channel to toggle indexing for")
@app_commands.default_permissions(administrator=True)
async def toggle_index(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
) -> None:
    """Toggle is_indexed flag for a channel."""
    await interaction.response.defer(ephemeral=True)
    
    # TODO: Update is_indexed in database
    # For now, just acknowledge
    
    await interaction.followup.send(
        f"Indexing toggled for {channel.mention}. "
        f"(Database update not yet implemented)",
        ephemeral=True,
    )


# =============================================================================
# ENTRY POINT
# =============================================================================

def main() -> None:
    """Run the bot."""
    settings = get_bot_settings()
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
