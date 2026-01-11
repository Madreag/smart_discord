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

# Note: DM conversation history is now stored in PostgreSQL + Qdrant (RAG memory)

# Deduplication cache for processed messages (prevents double responses)
_processed_messages: set[int] = set()
_MAX_CACHE_SIZE = 1000

# Whitelisted attachment extensions (security)
ALLOWED_EXTENSIONS = {
    ".pdf": "pdf",
    ".txt": "text",
    ".md": "markdown",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
}

# Blocked extensions (executables - security)
BLOCKED_EXTENSIONS = {".exe", ".bat", ".sh", ".ps1", ".dll", ".so", ".bin"}


def _detect_attachment_type(attachment: "discord.Attachment") -> str | None:
    """
    Detect source type from attachment.
    
    Returns None if file type is not whitelisted.
    CRITICAL: This is a security check - reject blocked types.
    """
    import os
    
    ext = os.path.splitext(attachment.filename.lower())[1]
    
    # Block dangerous extensions
    if ext in BLOCKED_EXTENSIONS:
        print(f"[SECURITY] Blocked attachment: {attachment.filename}")
        return None
    
    # Check whitelist
    if ext in ALLOWED_EXTENSIONS:
        return ALLOWED_EXTENSIONS[ext]
    
    # Check content_type fallback
    content_type = (attachment.content_type or "").lower()
    if "pdf" in content_type:
        return "pdf"
    elif "image/" in content_type:
        return "image"
    elif "text/plain" in content_type:
        return "text"
    elif "markdown" in content_type:
        return "markdown"
    
    return None


def _queue_attachment_processing(
    attachment: "discord.Attachment",
    guild_id: int,
    channel_id: int,
) -> None:
    """
    Queue attachment for processing via Celery.
    
    CRITICAL: NO file download here - only metadata to Redis.
    The actual download happens in the API worker.
    """
    try:
        from apps.bot.src.tasks import process_attachment
        
        process_attachment.delay({
            "attachment_id": attachment.id,
            "message_id": attachment.id,  # Will be set correctly in save_message_to_db
            "guild_id": guild_id,
            "channel_id": channel_id,
            "url": attachment.url,
            "proxy_url": attachment.proxy_url,
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "size_bytes": attachment.size,
        })
        print(f"[ATTACHMENT] Queued {attachment.filename} for processing")
    except Exception as e:
        print(f"[ERROR] Failed to queue attachment: {e}")


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
            
            # Save attachments (metadata only - NO file download in bot!)
            for attachment in message.attachments:
                # Detect source type from content_type/filename
                source_type = _detect_attachment_type(attachment)
                
                # Only save whitelisted types
                if source_type:
                    conn.execute(text("""
                        INSERT INTO attachments (id, message_id, guild_id, channel_id, url, proxy_url,
                                                 filename, content_type, size_bytes, source_type,
                                                 processing_status, created_at, updated_at)
                        VALUES (:id, :message_id, :guild_id, :channel_id, :url, :proxy_url,
                                :filename, :content_type, :size_bytes, :source_type,
                                'pending', NOW(), NOW())
                        ON CONFLICT (id) DO NOTHING
                    """), {
                        "id": attachment.id,
                        "message_id": message.id,
                        "guild_id": message.guild.id,
                        "channel_id": message.channel.id,
                        "url": attachment.url,
                        "proxy_url": attachment.proxy_url,
                        "filename": attachment.filename,
                        "content_type": attachment.content_type,
                        "size_bytes": attachment.size,
                        "source_type": source_type,
                    })
                    
                    # Queue for processing via Celery (NO blocking I/O here!)
                    _queue_attachment_processing(attachment, message.guild.id, message.channel.id)
            
            conn.commit()
            
            # Queue real-time indexing to Qdrant (non-blocking)
            # Skip bot messages and empty content
            if not message.author.bot and message.content and message.content.strip():
                _queue_message_for_indexing(message)
            
            return True
    except Exception as e:
        print(f"Error saving message to DB: {e}")
        return False


def _queue_message_for_indexing(message: "discord.Message") -> None:
    """
    Queue a message for real-time indexing to Qdrant.
    
    This enables immediate searchability of new messages.
    """
    try:
        from apps.bot.src.tasks import index_single_message
        
        index_single_message.delay(
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            channel_name=message.channel.name,
            message_id=message.id,
        )
    except Exception as e:
        # Don't fail message save if indexing queue fails
        print(f"[WARNING] Failed to queue message for indexing: {e}")


# Bot setup with required intents
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True  # Required to receive message events
intents.guilds = True
intents.members = True


class IntelligenceBot(commands.Bot):
    """Discord bot for community intelligence with rate limit handling."""
    
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
    
    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        """Handle errors including rate limits gracefully."""
        import sys
        import traceback
        
        exc_type, exc_value, exc_tb = sys.exc_info()
        
        if isinstance(exc_value, discord.HTTPException):
            if exc_value.status == 429:
                # Rate limited - log and let discord.py handle retry
                retry_after = getattr(exc_value, 'retry_after', 5)
                print(f"[RATELIMIT] Rate limited in {event_method}, retry after {retry_after}s")
                return
            elif exc_value.status >= 500:
                # Discord server error - log but don't crash
                print(f"[ERROR] Discord server error in {event_method}: {exc_value}")
                return
        
        # Log other errors
        print(f"[ERROR] Exception in {event_method}:")
        traceback.print_exception(exc_type, exc_value, exc_tb)
    
    async def on_command_error(self, ctx, error) -> None:
        """Handle command errors including rate limits."""
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏰ Please wait {error.retry_after:.1f}s before using this command again.",
                delete_after=5,
            )
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You don't have permission to use this command.", delete_after=5)
        else:
            print(f"[ERROR] Command error: {error}")


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
    global _processed_messages
    
    try:
        # Handle DMs separately (only from humans)
        if not message.guild:
            if not message.author.bot:
                await handle_dm(message)
            return
        
        # Save ALL messages to PostgreSQL (including bot messages for recall)
        save_message_to_db(message)
        
        # Don't process bot messages further (no responses to self)
        if message.author.bot:
            return
        
        # Deduplication: Skip if we've already processed this message
        if message.id in _processed_messages:
            print(f"[DEBUG] Skipping duplicate message {message.id}")
            return
        
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
            # Mark as processed BEFORE responding to prevent duplicates
            _processed_messages.add(message.id)
            
            # Clean up cache if too large
            if len(_processed_messages) > _MAX_CACHE_SIZE:
                # Remove oldest entries (convert to list, slice, convert back)
                _processed_messages = set(list(_processed_messages)[-500:])
            
            print(f"Bot mentioned by {message.author}: {message.content}")
            await handle_mention(message)
            
    except Exception as e:
        print(f"[ERROR] on_message error: {e}")


async def handle_dm(message: discord.Message) -> None:
    """
    Handle Direct Messages with RAG-based long-term memory.
    
    Memory is stored in PostgreSQL + Qdrant for semantic retrieval.
    """
    user_id = message.author.id
    question = message.content.strip()
    
    if not question:
        return
    
    print(f"[DM] {message.author}: {question}")
    
    # Find a mutual guild with the user for pre-prompt injection
    mutual_guild_id = None
    for guild in bot.guilds:
        if guild.get_member(user_id):
            mutual_guild_id = guild.id
            break
    
    # Show typing indicator while processing
    async with message.channel.typing():
        try:
            # Call API - memory storage happens server-side
            payload = {
                "user_id": user_id,
                "message": question,
            }
            if mutual_guild_id:
                payload["guild_id"] = mutual_guild_id
            
            async with httpx.AsyncClient() as client:
                api_response = await client.post(
                    "http://localhost:8000/chat",
                    json=payload,
                    timeout=60.0,
                )
                api_response.raise_for_status()
                response = api_response.json()
            
            answer = response.get("answer", "Sorry, I couldn't process that.")
            
            # Send response (no embed for cleaner DM experience)
            await message.reply(answer[:2000])
            
        except Exception as e:
            print(f"[DM ERROR] {e}")
            await message.reply(f"Sorry, I encountered an error: {str(e)}")


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
    
    # Check for attachments and enhance query with file context
    if message.attachments:
        attachment_names = [a.filename for a in message.attachments]
        # Append attachment context to help vector search find document chunks
        question = f"{question} [Attachments: {', '.join(attachment_names)}]"
        print(f"[MENTION] Query with attachments: {question}")
    
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
            import traceback
            error_msg = str(e) or type(e).__name__
            print(f"[MENTION ERROR] {error_msg}")
            traceback.print_exc()
            await message.reply(f"Sorry, I encountered an error: {error_msg}")


@bot.event
async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent) -> None:
    """
    Handle message deletion (Right to be Forgotten).
    
    Uses raw event to catch ALL deletions, not just cached messages.
    
    Pipeline:
    1. Soft delete in Postgres (preserve stats, clear content)
    2. Delete ALL Qdrant sessions containing this message (complete removal)
    3. Clear qdrant_point_id so remaining messages can be re-indexed
    
    GDPR/CCPA Compliance: Deleted message content must not appear in RAG responses.
    """
    if not payload.guild_id:
        return
    
    message_id = payload.message_id
    guild_id = payload.guild_id
    
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            # Step 1: Soft delete message in Postgres and clear content
            result = conn.execute(text("""
                UPDATE messages 
                SET 
                    is_deleted = TRUE,
                    deleted_at = NOW(),
                    updated_at = NOW(),
                    content = '[deleted]'
                WHERE id = :message_id 
                  AND guild_id = :guild_id
                RETURNING qdrant_point_id
            """), {
                "message_id": message_id,
                "guild_id": guild_id,
            })
            
            row = result.fetchone()
            
            # Step 2: Get and delete attachments (Right to be Forgotten)
            attach_result = conn.execute(text("""
                UPDATE attachments
                SET is_deleted = TRUE, deleted_at = NOW(), updated_at = NOW()
                WHERE message_id = :message_id AND guild_id = :guild_id
                RETURNING id, qdrant_point_ids
            """), {
                "message_id": message_id,
                "guild_id": guild_id,
            })
            attachment_rows = attach_result.fetchall()
            
            conn.commit()
            
            # Step 3: Queue comprehensive Qdrant session deletion
            # This finds and deletes ALL sessions containing this message
            from apps.bot.src.tasks import delete_sessions_for_messages
            delete_sessions_for_messages.delay(
                guild_id=guild_id,
                message_ids=[message_id],
            )
            print(f"[DELETE] Queued session deletion for message {message_id}")
            
            # Step 4: Queue Qdrant deletion for attachments
            for attach_row in attachment_rows:
                if attach_row.qdrant_point_ids:
                    from apps.bot.src.tasks import delete_attachment_vectors
                    delete_attachment_vectors.delay({
                        "attachment_id": attach_row.id,
                        "guild_id": guild_id,
                        "qdrant_point_ids": [str(pid) for pid in attach_row.qdrant_point_ids],
                    })
                    print(f"[DELETE] Queued Qdrant deletion for attachment {attach_row.id}")
                
    except Exception as e:
        print(f"[ERROR] on_raw_message_delete: {e}")


@bot.event
async def on_raw_bulk_message_delete(payload: discord.RawBulkMessageDeleteEvent) -> None:
    """
    Handle bulk message deletion (e.g., channel purge).
    
    More efficient than handling each message individually.
    Uses comprehensive session deletion for GDPR/CCPA compliance.
    """
    if not payload.guild_id:
        return
    
    message_ids = list(payload.message_ids)
    guild_id = payload.guild_id
    
    if not message_ids:
        return
    
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            # Bulk soft delete in Postgres
            result = conn.execute(text("""
                UPDATE messages 
                SET 
                    is_deleted = TRUE,
                    deleted_at = NOW(),
                    updated_at = NOW(),
                    content = '[deleted]'
                WHERE id = ANY(:message_ids)
                  AND guild_id = :guild_id
                RETURNING id, qdrant_point_id
            """), {
                "message_ids": message_ids,
                "guild_id": guild_id,
            })
            
            rows = result.fetchall()
            
            # Also delete attachments for these messages
            conn.execute(text("""
                UPDATE attachments
                SET is_deleted = TRUE, deleted_at = NOW(), updated_at = NOW()
                WHERE message_id = ANY(:message_ids) AND guild_id = :guild_id
            """), {
                "message_ids": message_ids,
                "guild_id": guild_id,
            })
            
            conn.commit()
            
            # Queue comprehensive session deletion for all deleted messages
            # This is more efficient than individual deletions
            from apps.bot.src.tasks import delete_sessions_for_messages
            delete_sessions_for_messages.delay(
                guild_id=guild_id,
                message_ids=message_ids,
            )
            
            print(f"[BULK DELETE] Soft-deleted {len(rows)} messages, queued session cleanup")
                
    except Exception as e:
        print(f"[ERROR] on_raw_bulk_message_delete: {e}")


@bot.event
async def on_raw_message_edit(payload: discord.RawMessageUpdateEvent) -> None:
    """
    Handle message edits - update Postgres and mark for re-indexing.
    
    Uses raw event for reliability (catches edits on uncached messages).
    
    Pipeline:
    1. Check if content actually changed
    2. Update content in Postgres
    3. Mark message as stale (needs re-indexing)
    """
    if not payload.guild_id:
        return
    
    # Get message data from payload
    data = payload.data
    message_id = payload.message_id
    guild_id = payload.guild_id
    
    # Check if this is a content edit (not just embed update)
    new_content = data.get("content")
    if new_content is None:
        return
    
    # Skip bot messages
    author = data.get("author", {})
    if author.get("bot", False):
        return
    
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            # Get old content and check if it changed
            old_result = conn.execute(text("""
                SELECT content, qdrant_point_id
                FROM messages
                WHERE id = :message_id AND guild_id = :guild_id
            """), {"message_id": message_id, "guild_id": guild_id})
            
            old_row = old_result.fetchone()
            
            if not old_row:
                # Message not in our DB - might be from before bot joined
                return
            
            old_content = old_row.content
            qdrant_point_id = old_row.qdrant_point_id
            
            # Skip if content hasn't changed
            if old_content == new_content:
                return
            
            # Update content in Postgres (updated_at > indexed_at marks it as stale)
            conn.execute(text("""
                UPDATE messages
                SET content = :content, updated_at = NOW()
                WHERE id = :message_id AND guild_id = :guild_id
            """), {
                "content": new_content,
                "message_id": message_id,
                "guild_id": guild_id,
            })
            conn.commit()
            
            print(f"[EDIT] Updated message {message_id} in Postgres")
            
            # If message was indexed, it's now stale and will be re-indexed
            # by the periodic sync job (updated_at > indexed_at)
            if qdrant_point_id:
                print(f"[EDIT] Message {message_id} marked stale for re-indexing")
                
    except Exception as e:
        print(f"[ERROR] on_raw_message_edit: {e}")


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
    
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            # Get current status
            result = conn.execute(text("""
                SELECT is_indexed FROM channels WHERE id = :channel_id
            """), {"channel_id": channel.id})
            row = result.fetchone()
            
            if row is None:
                # Channel not in DB, insert it with indexing enabled
                conn.execute(text("""
                    INSERT INTO channels (id, guild_id, name, is_indexed, created_at, updated_at)
                    VALUES (:channel_id, :guild_id, :name, TRUE, NOW(), NOW())
                """), {
                    "channel_id": channel.id,
                    "guild_id": interaction.guild.id,
                    "name": channel.name,
                })
                new_status = True
            else:
                # Toggle the status
                current_status = row[0]
                new_status = not current_status
                conn.execute(text("""
                    UPDATE channels SET is_indexed = :new_status, updated_at = NOW()
                    WHERE id = :channel_id
                """), {
                    "channel_id": channel.id,
                    "new_status": new_status,
                })
            
            conn.commit()
        
        status_text = "✅ **Enabled**" if new_status else "❌ **Disabled**"
        await interaction.followup.send(
            f"Indexing for {channel.mention}: {status_text}",
            ephemeral=True,
        )
        
    except Exception as e:
        await interaction.followup.send(
            f"Error updating indexing: {str(e)}",
            ephemeral=True,
        )


@bot.tree.command(name="summary", description="Summarize recent channel activity")
@app_commands.describe(
    channel="Channel to summarize (default: current)",
    hours="Hours to look back (default: 24, max: 168)",
)
@app_commands.checks.cooldown(1, 60.0, key=lambda i: (i.guild_id, i.user.id))
async def summary(
    interaction: discord.Interaction,
    channel: Optional[discord.TextChannel] = None,
    hours: int = 24,
) -> None:
    """Generate a summary of recent channel activity."""
    await interaction.response.defer(thinking=True)
    
    hours = min(max(hours, 1), 168)
    target_channel = channel or interaction.channel
    
    try:
        async with httpx.AsyncClient() as client:
            api_response = await client.post(
                "http://localhost:8000/summary",
                json={
                    "guild_id": interaction.guild.id,
                    "channel_id": target_channel.id,
                    "hours": hours,
                },
                timeout=90.0,
            )
            api_response.raise_for_status()
            data = api_response.json()
        
        if data.get("status") == "no_messages":
            await interaction.followup.send(
                f"📭 No messages found in {target_channel.mention} in the last {hours} hours.",
                ephemeral=True,
            )
            return
        
        embed = discord.Embed(
            title=f"📋 Summary: #{target_channel.name}",
            description=data.get("summary", "No summary available")[:4000],
            color=discord.Color.green(),
        )
        
        embed.add_field(
            name="📊 Stats",
            value=f"**Messages**: {data.get('message_count', 0)}\n"
                  f"**Participants**: {data.get('participant_count', 0)}\n"
                  f"**Time Range**: Last {hours}h",
            inline=True,
        )
        
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


@bot.tree.command(name="search", description="Search chat history")
@app_commands.describe(
    query="Search terms or keywords",
    channel="Limit search to specific channel (optional)",
    limit="Max results (default: 5, max: 10)",
)
@app_commands.checks.cooldown(1, 10.0, key=lambda i: (i.guild_id, i.user.id))
async def search(
    interaction: discord.Interaction,
    query: str,
    channel: Optional[discord.TextChannel] = None,
    limit: int = 5,
) -> None:
    """Search chat history using semantic search."""
    await interaction.response.defer(thinking=True)
    
    limit = min(max(limit, 1), 10)
    
    try:
        async with httpx.AsyncClient() as client:
            api_response = await client.post(
                "http://localhost:8000/search",
                json={
                    "query": query,
                    "guild_id": interaction.guild.id,
                    "channel_id": channel.id if channel else None,
                    "limit": limit,
                },
                timeout=30.0,
            )
            api_response.raise_for_status()
            data = api_response.json()
        
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
            content = result.get("content", "")[:200]
            if len(result.get("content", "")) > 200:
                content += "..."
            
            author = result.get("author", "Unknown")
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


@bot.tree.command(name="topics", description="Show trending topics in the server")
@app_commands.describe(
    days="Days to analyze (default: 7, max: 30)",
)
@app_commands.checks.cooldown(1, 30.0, key=lambda i: (i.guild_id, i.user.id))
async def topics(
    interaction: discord.Interaction,
    days: int = 7,
) -> None:
    """Show trending topics using keyword extraction."""
    await interaction.response.defer(thinking=True)
    
    days = min(max(days, 1), 30)
    
    try:
        async with httpx.AsyncClient() as client:
            api_response = await client.get(
                f"http://localhost:8000/guilds/{interaction.guild.id}/topics",
                params={"days": days},
                timeout=60.0,
            )
            api_response.raise_for_status()
            data = api_response.json()
        
        topic_list = data.get("topics", [])
        
        if not topic_list:
            await interaction.followup.send(
                "🏷️ No trending topics found. Try increasing the time range.",
                ephemeral=True,
            )
            return
        
        embed = discord.Embed(
            title=f"🏷️ Trending Topics (Last {days} days)",
            color=discord.Color.purple(),
        )
        
        topic_lines = []
        for i, topic in enumerate(topic_list[:10], 1):
            name = topic.get("name", "Unknown")
            count = topic.get("count", 0)
            topic_lines.append(f"{i}. **{name}** ({count} mentions)")
        
        embed.description = "\n".join(topic_lines)
        embed.set_footer(text=f"Analyzed {data.get('message_count', 0)} messages")
        
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        await interaction.followup.send(
            f"❌ Error fetching topics: {str(e)[:100]}",
            ephemeral=True,
        )


# =============================================================================
# APP COMMAND ERROR HANDLER
# =============================================================================

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Handle slash command errors including cooldowns."""
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"⏰ Please wait **{error.retry_after:.0f}s** before using this command again.",
            ephemeral=True,
        )
    elif isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.",
            ephemeral=True,
        )
    else:
        print(f"[ERROR] App command error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"❌ An error occurred: {str(error)[:100]}",
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
