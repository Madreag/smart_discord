"""
Pre-prompt utility for fetching guild personality/rules.
"""

from typing import Optional


def get_guild_pre_prompt(guild_id: int) -> Optional[str]:
    """
    Fetch the pre-prompt for a guild from the database.
    
    Args:
        guild_id: The Discord guild ID
        
    Returns:
        The pre-prompt text if set, None otherwise
    """
    try:
        from sqlalchemy import create_engine, text as sql_text
        from apps.api.src.core.config import get_settings
        
        settings = get_settings()
        sync_url = settings.database_url.replace("+asyncpg", "")
        engine = create_engine(sync_url, pool_pre_ping=True)
        
        with engine.connect() as conn:
            result = conn.execute(sql_text(
                "SELECT pre_prompt FROM guilds WHERE id = :guild_id"
            ), {"guild_id": guild_id})
            row = result.fetchone()
            
            if row and row[0]:
                return row[0]
    except Exception:
        pass
    
    return None
