"""
Backfill historical Discord messages into PostgreSQL.

Usage:
    python scripts/backfill_messages.py --guild-id YOUR_GUILD_ID --limit 1000

This script fetches historical messages from all text channels in a guild
and saves them to the PostgreSQL database.
"""

import asyncio
import argparse
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

import discord
from sqlalchemy import create_engine, text

from apps.bot.src.config import get_bot_settings


def get_db_engine():
    """Get database engine."""
    settings = get_bot_settings()
    sync_url = settings.database_url.replace("+asyncpg", "")
    return create_engine(sync_url, pool_pre_ping=True)


def save_message(conn, message: discord.Message) -> bool:
    """Save a single message to the database."""
    try:
        # Upsert user
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
        return True
    except Exception as e:
        print(f"  Error saving message {message.id}: {e}")
        return False


class BackfillBot(discord.Client):
    """Simple bot client for backfilling messages."""
    
    def __init__(self, guild_id: int, limit_per_channel: int):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        super().__init__(intents=intents)
        
        self.target_guild_id = guild_id
        self.limit_per_channel = limit_per_channel
        self.engine = get_db_engine()
        self.total_saved = 0
    
    async def on_ready(self):
        print(f"Logged in as {self.user}")
        
        guild = self.get_guild(self.target_guild_id)
        if not guild:
            print(f"Error: Guild {self.target_guild_id} not found")
            await self.close()
            return
        
        print(f"Backfilling messages for: {guild.name}")
        
        with self.engine.connect() as conn:
            # Upsert guild
            conn.execute(text("""
                INSERT INTO guilds (id, name, owner_id, joined_at, created_at, updated_at)
                VALUES (:id, :name, :owner_id, NOW(), NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    updated_at = NOW()
            """), {
                "id": guild.id,
                "name": guild.name,
                "owner_id": guild.owner_id,
            })
            conn.commit()
            
            # Process each text channel
            for channel in guild.text_channels:
                try:
                    # Upsert channel
                    conn.execute(text("""
                        INSERT INTO channels (id, guild_id, name, type, created_at, updated_at)
                        VALUES (:id, :guild_id, :name, :type, NOW(), NOW())
                        ON CONFLICT (id) DO UPDATE SET
                            name = EXCLUDED.name,
                            updated_at = NOW()
                    """), {
                        "id": channel.id,
                        "guild_id": guild.id,
                        "name": channel.name,
                        "type": channel.type.value,
                    })
                    conn.commit()
                    
                    print(f"\nProcessing #{channel.name}...")
                    count = 0
                    
                    async for message in channel.history(limit=self.limit_per_channel):
                        # Include bot messages so we can recall past answers
                        if save_message(conn, message):
                            count += 1
                            self.total_saved += 1
                        
                        if count % 100 == 0 and count > 0:
                            conn.commit()
                            print(f"  Saved {count} messages...")
                    
                    conn.commit()
                    print(f"  Completed: {count} messages saved")
                    
                except discord.Forbidden:
                    print(f"  Skipped #{channel.name} (no permission)")
                except Exception as e:
                    print(f"  Error in #{channel.name}: {e}")
        
        print(f"\n{'='*50}")
        print(f"Backfill complete! Total messages saved: {self.total_saved}")
        print(f"{'='*50}")
        
        await self.close()


async def main():
    parser = argparse.ArgumentParser(description="Backfill Discord messages to PostgreSQL")
    parser.add_argument("--guild-id", type=int, required=True, help="Discord Guild ID to backfill")
    parser.add_argument("--limit", type=int, default=500, help="Max messages per channel (default: 500)")
    args = parser.parse_args()
    
    settings = get_bot_settings()
    
    print(f"Starting backfill for guild {args.guild_id}")
    print(f"Limit per channel: {args.limit}")
    print()
    
    bot = BackfillBot(args.guild_id, args.limit)
    await bot.start(settings.discord_token)


if __name__ == "__main__":
    asyncio.run(main())
