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

from apps.bot.src.config import get_bot_settings
from apps.bot.src.tasks import celery_app, index_messages, delete_message_vector, ask_query
from packages.shared.python.models import IndexTaskPayload, DeleteTaskPayload


# Bot setup with required intents
intents = discord.Intents.default()
intents.message_content = True
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

@bot.event
async def on_message(message: discord.Message) -> None:
    """
    Handle incoming messages.
    
    Stores message in Postgres and queues for vector indexing
    if the channel has is_indexed=True.
    """
    # Ignore bot messages
    if message.author.bot:
        return
    
    # Ignore DMs
    if not message.guild:
        return
    
    # TODO: Check if channel.is_indexed in database
    # For now, we'll push all messages to the task queue
    
    # Queue indexing task (non-blocking)
    payload = IndexTaskPayload(
        guild_id=message.guild.id,
        channel_id=message.channel.id,
        message_ids=[message.id],
    )
    
    # Send to Celery (fire and forget)
    index_messages.delay(payload.model_dump())
    
    # Process commands if any
    await bot.process_commands(message)


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
        
        # Queue the query task and wait for result
        result = ask_query.delay(
            guild_id=interaction.guild.id,
            query=question,
            channel_ids=channel_ids,
        )
        
        # Wait for result (with timeout)
        response = result.get(timeout=60)
        
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
        # Quick stats query
        result = ask_query.delay(
            guild_id=interaction.guild.id,
            query="How many messages total and who are the top 5 most active users?",
        )
        
        response = result.get(timeout=30)
        
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
