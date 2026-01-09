"""
Analytics Agent: Text-to-SQL for Discord Message Analytics

Converts natural language queries about Discord activity into SQL queries
that run against the PostgreSQL read-only replica.

SECURITY: All generated SQL is validated by sql_validator before execution.
INVARIANT: Queries always filter by guild_id for multi-tenant isolation.
"""

import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from packages.shared.python.models import AskResponse, MessageSource, RouterIntent
from apps.api.src.agents.sql_validator import validate_sql, validate_and_enforce_guild_filter, ValidationResult


# Schema context for the LLM
SCHEMA_CONTEXT = """
You have access to a PostgreSQL database with the following tables:

TABLE: messages
- id (BIGINT): Discord message snowflake ID
- channel_id (BIGINT): Discord channel ID
- guild_id (BIGINT): Discord guild/server ID (ALWAYS filter by this)
- author_id (BIGINT): Discord user ID of message author
- content (TEXT): Message text content
- reply_to_id (BIGINT, nullable): ID of message being replied to
- message_timestamp (TIMESTAMPTZ): When the message was sent
- is_deleted (BOOLEAN): Soft delete flag

TABLE: channels
- id (BIGINT): Discord channel snowflake ID
- guild_id (BIGINT): Discord guild/server ID
- name (VARCHAR): Channel name
- is_indexed (BOOLEAN): Whether channel is indexed for search

TABLE: users
- id (BIGINT): Discord user snowflake ID
- username (VARCHAR): Discord username
- global_name (VARCHAR, nullable): Display name

TABLE: guild_members
- guild_id (BIGINT): Guild ID
- user_id (BIGINT): User ID
- nickname (VARCHAR, nullable): Server nickname
- message_count (INT): Cached message count
- last_message_at (TIMESTAMPTZ): Last activity timestamp

IMPORTANT RULES:
1. ALWAYS filter by guild_id = {guild_id} for security
2. Only generate SELECT statements
3. Use message_timestamp for time-based queries
4. Join with users table to get usernames
5. Exclude is_deleted = TRUE messages
"""


async def generate_sql(query: str, guild_id: int) -> str:
    """
    Generate SQL from natural language query using LLM.
    
    Falls back to a template-based approach if LLM is unavailable.
    """
    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        
        from apps.api.src.core.config import get_settings
        from apps.api.src.core.llm_factory import get_llm
        
        settings = get_settings()
        if not settings.active_llm_api_key:
            return _fallback_sql_generation(query, guild_id)
        
        llm = get_llm(temperature=0.0)
        
        system_prompt = f"""You are a SQL query generator for Discord analytics.
{SCHEMA_CONTEXT.format(guild_id=guild_id)}

Generate a single SELECT query to answer the user's question.
Respond with ONLY the SQL query, no explanation or markdown."""

        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=query),
        ])
        
        return response.content.strip().strip("`").replace("sql\n", "").strip()
        
    except ImportError:
        return _fallback_sql_generation(query, guild_id)
    except Exception:
        return _fallback_sql_generation(query, guild_id)


def _fallback_sql_generation(query: str, guild_id: int) -> str:
    """
    Template-based SQL generation for common query patterns.
    Used when LLM is unavailable.
    """
    query_lower = query.lower()
    
    # Who spoke most / most active users
    if "who spoke" in query_lower or "most active" in query_lower or "most messages" in query_lower:
        return f"""
            SELECT u.username, u.global_name, COUNT(m.id) as message_count
            FROM messages m
            JOIN users u ON m.author_id = u.id
            WHERE m.guild_id = {guild_id} AND m.is_deleted = FALSE
            GROUP BY u.id, u.username, u.global_name
            ORDER BY message_count DESC
            LIMIT 10
        """
    
    # Message count queries
    if "how many messages" in query_lower:
        if "last week" in query_lower:
            return f"""
                SELECT COUNT(*) as message_count
                FROM messages
                WHERE guild_id = {guild_id} 
                  AND is_deleted = FALSE
                  AND message_timestamp >= NOW() - INTERVAL '7 days'
            """
        return f"""
            SELECT COUNT(*) as message_count
            FROM messages
            WHERE guild_id = {guild_id} AND is_deleted = FALSE
        """
    
    # Most active channel
    if "most active channel" in query_lower or "active channel" in query_lower:
        return f"""
            SELECT c.name as channel_name, COUNT(m.id) as message_count
            FROM messages m
            JOIN channels c ON m.channel_id = c.id
            WHERE m.guild_id = {guild_id} AND m.is_deleted = FALSE
            GROUP BY c.id, c.name
            ORDER BY message_count DESC
            LIMIT 10
        """
    
    # Message counts by user
    if "message count" in query_lower and "by user" in query_lower:
        return f"""
            SELECT u.username, COUNT(m.id) as message_count
            FROM messages m
            JOIN users u ON m.author_id = u.id
            WHERE m.guild_id = {guild_id} AND m.is_deleted = FALSE
            GROUP BY u.id, u.username
            ORDER BY message_count DESC
        """
    
    # Default: simple message count
    return f"""
        SELECT COUNT(*) as total_messages
        FROM messages
        WHERE guild_id = {guild_id} AND is_deleted = FALSE
    """


async def execute_analytics_query(
    query: str,
    guild_id: int,
    db_session: Optional[Any] = None
) -> tuple[ValidationResult, Optional[list[dict[str, Any]]]]:
    """
    Generate, validate, and execute an analytics SQL query.
    
    Args:
        query: Natural language query
        guild_id: Guild ID for multi-tenant filtering
        db_session: Optional database session (for testing)
        
    Returns:
        Tuple of (validation_result, query_results)
    """
    # Generate SQL from natural language
    generated_sql = await generate_sql(query, guild_id)
    
    # Validate and enforce guild_id filter
    validation = validate_and_enforce_guild_filter(generated_sql, guild_id)
    
    if not validation.is_valid:
        return (validation, None)
    
    # If no db session provided, return validation result only
    if db_session is None:
        return (validation, None)
    
    # Execute query (would use read-only replica in production)
    # This is a placeholder - actual implementation would use SQLAlchemy
    # result = await db_session.execute(text(validation.sanitized_sql))
    # rows = result.fetchall()
    
    return (validation, None)


async def process_analytics_query(
    query: str,
    guild_id: int,
) -> AskResponse:
    """
    Process an analytics query and return formatted response.
    
    This is the main entry point for the analytics agent.
    """
    validation, results = await execute_analytics_query(query, guild_id)
    
    if not validation.is_valid:
        return AskResponse(
            answer=f"Unable to process query: {validation.error}",
            sources=[],
            routed_to=RouterIntent.ANALYTICS_DB,
            execution_time_ms=0,
        )
    
    # Format results into response
    # In production, this would format the actual query results
    return AskResponse(
        answer=f"Query generated successfully. SQL: {validation.sanitized_sql}",
        sources=[],
        routed_to=RouterIntent.ANALYTICS_DB,
        execution_time_ms=0,
    )
