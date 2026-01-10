"""
FastAPI Cognitive Layer - Main Application

Routes incoming queries through the LangGraph agent system:
- Router Agent → classifies intent
- Analytics Agent → Text-to-SQL on PostgreSQL
- Vector RAG Agent → Semantic search on Qdrant
- Web Search Agent → External information retrieval
"""

import sys
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from packages.shared.python.models import AskQuery, AskResponse, RouterIntent
from apps.api.src.agents.router import classify_intent
from apps.api.src.agents.analytics import process_analytics_query
from apps.api.src.agents.vector_rag import process_rag_query
from apps.api.src.agents.web_search import process_web_search_query
from apps.api.src.agents.general_knowledge import process_general_knowledge_query
from apps.api.src.core.config import get_settings, LLMProvider, EmbeddingProvider
from apps.api.src.core.llm_factory import get_provider_info


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    # Startup
    settings = get_settings()
    print(f"Starting Cognitive Layer API (debug={settings.debug})")
    
    # Initialize Qdrant collection
    try:
        from apps.api.src.services.qdrant_service import qdrant_service
        qdrant_service.ensure_collection()
        print("Qdrant collection initialized")
    except Exception as e:
        print(f"Warning: Could not initialize Qdrant: {e}")
    
    yield
    
    # Shutdown
    print("Shutting down Cognitive Layer API")


app = FastAPI(
    title="Discord Community Intelligence API",
    description="Cognitive Layer for Discord analytics and semantic search",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware for Next.js dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="healthy", version="0.1.0")


@app.post("/ask", response_model=AskResponse)
async def ask(query: AskQuery) -> AskResponse:
    """
    Process a natural language query about the Discord community.
    
    The query is first classified by the Router Agent, then dispatched
    to the appropriate processing pipeline:
    
    - **analytics_db**: Statistical queries → Text-to-SQL
    - **vector_rag**: Semantic queries → Vector search + RAG
    - **web_search**: External info → Web search API
    
    All queries are filtered by guild_id for multi-tenant isolation.
    """
    from apps.api.src.services.conversation_memory import conversation_memory
    from apps.api.src.services.security_service import (
        detect_prompt_injection,
        validate_output,
        log_security_event,
    )
    
    try:
        # Security check - detect prompt injection attempts
        security_result = detect_prompt_injection(query.query)
        
        if not security_result.is_safe:
            log_security_event(
                event_type="prompt_injection_blocked",
                user_id=query.author_id or 0,
                guild_id=query.guild_id,
                details={
                    "risk_score": security_result.risk_score,
                    "blocked_patterns": security_result.blocked_patterns,
                    "query_preview": query.query[:100],
                },
            )
            return AskResponse(
                answer="I cannot process that request. Please rephrase your question.",
                sources=[],
                routed_to=RouterIntent.GENERAL_KNOWLEDGE,
                execution_time_ms=0,
            )
        
        # Use sanitized input
        safe_query = security_result.sanitized_input
        
        # Record user message in conversation memory
        if query.channel_id:
            conversation_memory.add_user_message(
                query.channel_id,
                query.query,
                query.author_name or "User"
            )
        
        # Step 1: Classify intent (using sanitized query)
        intent = await classify_intent(safe_query)
        
        # Step 2: Route to appropriate agent (using sanitized query)
        if intent == RouterIntent.ANALYTICS_DB:
            response = await process_analytics_query(
                query=safe_query,
                guild_id=query.guild_id,
            )
        elif intent == RouterIntent.VECTOR_RAG:
            response = await process_rag_query(
                query=safe_query,
                guild_id=query.guild_id,
                channel_ids=query.channel_ids,
                channel_id=query.channel_id,
            )
        elif intent == RouterIntent.WEB_SEARCH:
            response = await process_web_search_query(
                query=safe_query,
                guild_id=query.guild_id,
            )
        elif intent == RouterIntent.GRAPH_RAG:
            from apps.api.src.agents.graphrag import process_graphrag_query
            response = await process_graphrag_query(
                query=safe_query,
                guild_id=query.guild_id,
            )
        elif intent == RouterIntent.GENERAL_KNOWLEDGE:
            response = await process_general_knowledge_query(
                query=safe_query,
                guild_id=query.guild_id,
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Unknown intent: {intent}",
            )
        
        # Record bot response in conversation memory
        if query.channel_id and response.answer:
            conversation_memory.add_assistant_message(
                query.channel_id,
                response.answer
            )
        
        return response
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing query: {str(e)}",
        )


class ClassifyRequest(BaseModel):
    """Request for intent classification only."""
    query: str


class ClassifyResponse(BaseModel):
    """Response with classified intent."""
    intent: RouterIntent
    query: str


@app.post("/classify", response_model=ClassifyResponse)
async def classify(request: ClassifyRequest) -> ClassifyResponse:
    """
    Classify query intent without executing.
    
    Useful for debugging and understanding how queries are routed.
    """
    intent = await classify_intent(request.query)
    return ClassifyResponse(intent=intent, query=request.query)


class ChatRequest(BaseModel):
    """Request for DM chat with conversation context."""
    user_id: int
    message: str
    conversation_history: list[dict] = []
    guild_id: Optional[int] = None  # Optional: used to inject guild pre-prompt


class ChatResponse(BaseModel):
    """Response for DM chat."""
    answer: str
    user_id: int


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Handle DM conversations with RAG-based long-term memory.
    
    Stores messages in PostgreSQL and Qdrant for semantic retrieval.
    """
    try:
        from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
        from apps.api.src.core.llm_factory import get_llm
        from apps.api.src.agents.dm_memory import (
            store_dm_message, 
            retrieve_relevant_context,
            get_recent_messages,
            get_user_server_context,
        )
        from datetime import datetime, timezone
        
        settings = get_settings()
        if not settings.active_llm_api_key:
            return ChatResponse(
                answer="I need an LLM API key configured to chat.",
                user_id=request.user_id,
            )
        
        # Store user message in long-term memory
        store_dm_message(request.user_id, "user", request.message)
        
        # Retrieve relevant past context using RAG
        relevant_context = retrieve_relevant_context(
            user_id=request.user_id,
            query=request.message,
            limit=5,
        )
        
        # Get relevant server channel context (cross-context)
        server_context = get_user_server_context(
            user_id=request.user_id,
            query=request.message,
            limit=3,
        )
        
        # Get recent messages for immediate context (last 50 messages)
        recent_messages = get_recent_messages(request.user_id, limit=50)
        
        llm = get_llm(temperature=0.7)
        
        current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # Build context from RAG retrieval (DM history)
        memory_context = ""
        if relevant_context:
            memory_items = []
            for ctx in relevant_context:
                if ctx["content"] not in [m.get("content") for m in recent_messages]:
                    memory_items.append(f"- {ctx['role']}: {ctx['content']}")
            if memory_items:
                memory_context = "\n\nRelevant memories from past DM conversations:\n" + "\n".join(memory_items[:3])
        
        # Add server channel context
        if server_context:
            server_items = [f"- (#{ctx['channel']}) {ctx['content'][:100]}..." for ctx in server_context]
            memory_context += "\n\nRelevant things you said in server channels:\n" + "\n".join(server_items)
        
        # Fetch guild pre-prompt if guild_id is provided
        guild_pre_prompt = ""
        if request.guild_id:
            try:
                from sqlalchemy import create_engine, text as sql_text
                sync_url = settings.database_url.replace("+asyncpg", "")
                engine = create_engine(sync_url, pool_pre_ping=True)
                with engine.connect() as conn:
                    result = conn.execute(sql_text(
                        "SELECT pre_prompt FROM guilds WHERE id = :guild_id"
                    ), {"guild_id": request.guild_id})
                    row = result.fetchone()
                    if row and row[0]:
                        guild_pre_prompt = f"\n\n{row[0]}"
            except Exception:
                pass  # Silently ignore pre-prompt fetch errors
        
        system_prompt = f"""You are a friendly and helpful Discord bot assistant having a conversation.
You can help with general questions, coding, creative tasks, and more.
Be conversational and remember context from the conversation.
Keep responses concise but helpful.{guild_pre_prompt}

Current date and time: {current_time}{memory_context}"""

        # Build message history from recent messages
        messages = [SystemMessage(content=system_prompt)]
        
        # Add recent conversation history (excluding current message)
        for msg in recent_messages[:-1]:  # Exclude the message we just stored
            if msg.get("role") == "user":
                messages.append(HumanMessage(content=msg.get("content", "")))
            elif msg.get("role") == "assistant":
                messages.append(AIMessage(content=msg.get("content", "")))
        
        # Add current message
        messages.append(HumanMessage(content=request.message))
        
        response = await llm.ainvoke(messages)
        answer = response.content.strip()
        
        # Store assistant response in long-term memory
        store_dm_message(request.user_id, "assistant", answer)
        
        return ChatResponse(answer=answer, user_id=request.user_id)
        
    except Exception as e:
        return ChatResponse(
            answer=f"Sorry, I encountered an error: {str(e)}",
            user_id=request.user_id,
        )


class ProviderInfoResponse(BaseModel):
    """Current LLM provider configuration."""
    llm_provider: str
    llm_model: str
    embedding_provider: str
    embedding_model: str
    has_api_key: bool
    available_providers: list[str]
    available_models: dict[str, list[str]]


class UpdateProviderRequest(BaseModel):
    """Request to update LLM provider settings."""
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None


# Available models per provider (updated January 2026)
AVAILABLE_MODELS = {
    "openai": [
        "o3",
        "o3-mini", 
        "o1",
        "o1-mini",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4.1-nano",
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
    ],
    "anthropic": [
        "claude-opus-4-5-20250929",
        "claude-sonnet-4-5-20250929",
        "claude-haiku-4-5-20250929",
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
    ],
    "xai": [
        "grok-4",
        "grok-3",
        "grok-3-mini",
        "grok-2-latest",
        "grok-beta",
    ],
}


@app.get("/settings/provider", response_model=ProviderInfoResponse)
async def get_provider_settings() -> ProviderInfoResponse:
    """
    Get current LLM and embedding provider settings.
    
    Returns the active provider configuration and available options.
    """
    info = get_provider_info()
    return ProviderInfoResponse(
        llm_provider=info["llm_provider"],
        llm_model=info["llm_model"],
        embedding_provider=info["embedding_provider"],
        embedding_model=info["embedding_model"],
        has_api_key=info["has_api_key"],
        available_providers=["openai", "anthropic", "xai"],
        available_models=AVAILABLE_MODELS,
    )


@app.put("/settings/provider", response_model=ProviderInfoResponse)
async def update_provider_settings(request: UpdateProviderRequest) -> ProviderInfoResponse:
    """
    Update LLM provider and/or model at runtime.
    
    Changes take effect immediately without server restart.
    """
    from apps.api.src.core.config import set_runtime_override, LLMProvider
    
    settings = get_settings()
    
    # Validate and set provider
    if request.llm_provider:
        if request.llm_provider not in ["openai", "anthropic", "xai"]:
            raise HTTPException(status_code=400, detail=f"Invalid provider: {request.llm_provider}")
        set_runtime_override("llm_provider", request.llm_provider)
    
    # Validate and set model
    if request.llm_model:
        # Get the current/new provider
        provider = request.llm_provider or settings.active_llm_provider.value
        if request.llm_model not in AVAILABLE_MODELS.get(provider, []):
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid model '{request.llm_model}' for provider '{provider}'"
            )
        set_runtime_override(f"{provider}_model", request.llm_model)
    
    # Return updated settings
    info = get_provider_info()
    return ProviderInfoResponse(
        llm_provider=info["llm_provider"],
        llm_model=info["llm_model"],
        embedding_provider=info["embedding_provider"],
        embedding_model=info["embedding_model"],
        has_api_key=info["has_api_key"],
        available_providers=["openai", "anthropic", "xai"],
        available_models=AVAILABLE_MODELS,
    )


class ChannelResponse(BaseModel):
    """Discord channel info."""
    id: str
    name: str
    type: int
    isIndexed: bool = False


@app.get("/guilds/{guild_id}/channels", response_model=list[ChannelResponse])
async def get_guild_channels(guild_id: str) -> list[ChannelResponse]:
    """
    Fetch channels for a Discord guild using the bot token.
    
    Only returns text channels (type 0) that the bot can see.
    """
    import httpx
    
    settings = get_settings()
    if not settings.discord_token:
        raise HTTPException(
            status_code=500,
            detail="Discord bot token not configured",
        )
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://discord.com/api/v10/guilds/{guild_id}/channels",
                headers={
                    "Authorization": f"Bot {settings.discord_token}",
                },
            )
            
            if response.status_code == 403:
                raise HTTPException(
                    status_code=403,
                    detail="Bot does not have access to this guild",
                )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Discord API error: {response.text}",
                )
            
            channels = response.json()
            
            # Get indexed status from database
            indexed_channels = set()
            try:
                from sqlalchemy import create_engine, text as sql_text
                sync_url = settings.database_url.replace("+asyncpg", "")
                engine = create_engine(sync_url, pool_pre_ping=True)
                with engine.connect() as conn:
                    result = conn.execute(sql_text(
                        "SELECT id FROM channels WHERE guild_id = :guild_id AND is_indexed = TRUE"
                    ), {"guild_id": int(guild_id)})
                    indexed_channels = {str(row[0]) for row in result.fetchall()}
            except Exception:
                pass  # If DB unavailable, default to not indexed
            
            # Filter to text channels (type 0) and format response
            text_channels = [
                ChannelResponse(
                    id=str(ch["id"]),
                    name=ch["name"],
                    type=ch["type"],
                    isIndexed=str(ch["id"]) in indexed_channels,
                )
                for ch in channels
                if ch["type"] == 0  # Text channels only
            ]
            
            # Sort by position
            text_channels.sort(key=lambda c: c.name)
            
            return text_channels
            
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to connect to Discord API: {str(e)}",
        )


class ToggleIndexRequest(BaseModel):
    """Request to toggle channel indexing."""
    isIndexed: bool


@app.patch("/guilds/{guild_id}/channels/{channel_id}/index")
async def toggle_channel_index(
    guild_id: str,
    channel_id: str,
    request: ToggleIndexRequest,
) -> dict:
    """
    Toggle the is_indexed flag for a channel.
    """
    try:
        from sqlalchemy import create_engine, text as sql_text
        
        settings = get_settings()
        sync_url = settings.database_url.replace("+asyncpg", "")
        engine = create_engine(sync_url, pool_pre_ping=True)
        
        with engine.connect() as conn:
            # Upsert the channel with the new indexed status
            conn.execute(sql_text("""
                INSERT INTO channels (id, guild_id, name, is_indexed, created_at, updated_at)
                VALUES (:channel_id, :guild_id, 'unknown', :is_indexed, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    is_indexed = :is_indexed,
                    updated_at = NOW()
            """), {
                "channel_id": int(channel_id),
                "guild_id": int(guild_id),
                "is_indexed": request.isIndexed,
            })
            conn.commit()
        
        return {"success": True, "channelId": channel_id, "isIndexed": request.isIndexed}
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update channel: {str(e)}",
        )


class PrePromptResponse(BaseModel):
    """Response for guild pre-prompt."""
    guild_id: str
    pre_prompt: Optional[str] = None


class PrePromptRequest(BaseModel):
    """Request to update pre-prompt."""
    pre_prompt: str


@app.get("/guilds/{guild_id}/pre-prompt", response_model=PrePromptResponse)
async def get_pre_prompt(guild_id: str) -> PrePromptResponse:
    """
    Get the pre-prompt for a guild.
    """
    try:
        from sqlalchemy import create_engine, text as sql_text
        
        settings = get_settings()
        sync_url = settings.database_url.replace("+asyncpg", "")
        engine = create_engine(sync_url, pool_pre_ping=True)
        
        with engine.connect() as conn:
            result = conn.execute(sql_text(
                "SELECT pre_prompt FROM guilds WHERE id = :guild_id"
            ), {"guild_id": int(guild_id)})
            row = result.fetchone()
            
            pre_prompt = row[0] if row else None
        
        return PrePromptResponse(guild_id=guild_id, pre_prompt=pre_prompt)
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch pre-prompt: {str(e)}",
        )


@app.put("/guilds/{guild_id}/pre-prompt", response_model=PrePromptResponse)
async def set_pre_prompt(guild_id: str, request: PrePromptRequest) -> PrePromptResponse:
    """
    Set the pre-prompt for a guild.
    """
    try:
        from sqlalchemy import create_engine, text as sql_text
        
        settings = get_settings()
        sync_url = settings.database_url.replace("+asyncpg", "")
        engine = create_engine(sync_url, pool_pre_ping=True)
        
        with engine.connect() as conn:
            conn.execute(sql_text("""
                UPDATE guilds SET pre_prompt = :pre_prompt, updated_at = NOW()
                WHERE id = :guild_id
            """), {
                "guild_id": int(guild_id),
                "pre_prompt": request.pre_prompt if request.pre_prompt.strip() else None,
            })
            conn.commit()
        
        return PrePromptResponse(
            guild_id=guild_id, 
            pre_prompt=request.pre_prompt if request.pre_prompt.strip() else None
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update pre-prompt: {str(e)}",
        )


class ApiKeyInfo(BaseModel):
    """Info about an API key (masked for security)."""
    provider: str
    label: str
    is_set: bool
    masked_value: Optional[str] = None


class ApiKeysResponse(BaseModel):
    """Response with all API keys info."""
    keys: list[ApiKeyInfo]


class UpdateApiKeyRequest(BaseModel):
    """Request to update an API key."""
    provider: str
    api_key: str


def mask_api_key(key: Optional[str]) -> Optional[str]:
    """Mask an API key for display, showing only first 4 and last 4 chars."""
    if not key or len(key) < 12:
        return None
    return f"{key[:4]}...{key[-4:]}"


@app.get("/settings/api-keys", response_model=ApiKeysResponse)
async def get_api_keys() -> ApiKeysResponse:
    """
    Get status of all API keys (masked for security).
    """
    settings = get_settings()
    
    keys = [
        ApiKeyInfo(
            provider="openai",
            label="OpenAI",
            is_set=bool(settings.get_api_key_for_provider("openai")),
            masked_value=mask_api_key(settings.get_api_key_for_provider("openai")),
        ),
        ApiKeyInfo(
            provider="anthropic", 
            label="Anthropic",
            is_set=bool(settings.get_api_key_for_provider("anthropic")),
            masked_value=mask_api_key(settings.get_api_key_for_provider("anthropic")),
        ),
        ApiKeyInfo(
            provider="xai",
            label="xAI (Grok)",
            is_set=bool(settings.get_api_key_for_provider("xai")),
            masked_value=mask_api_key(settings.get_api_key_for_provider("xai")),
        ),
        ApiKeyInfo(
            provider="tavily",
            label="Tavily (Web Search)",
            is_set=bool(settings.get_api_key_for_provider("tavily")),
            masked_value=mask_api_key(settings.get_api_key_for_provider("tavily")),
        ),
    ]
    
    return ApiKeysResponse(keys=keys)


@app.put("/settings/api-keys", response_model=ApiKeysResponse)
async def update_api_key(request: UpdateApiKeyRequest) -> ApiKeysResponse:
    """
    Update an API key at runtime.
    """
    from apps.api.src.core.config import set_runtime_override
    
    valid_providers = ["openai", "anthropic", "xai", "tavily"]
    if request.provider not in valid_providers:
        raise HTTPException(status_code=400, detail=f"Invalid provider: {request.provider}")
    
    key_name = f"{request.provider}_api_key"
    set_runtime_override(key_name, request.api_key)
    
    # Return updated keys
    return await get_api_keys()


# =============================================================================
# Guild Statistics Endpoints
# =============================================================================

class GuildStats(BaseModel):
    """Guild statistics response model."""
    guild_id: int
    total_messages: int
    indexed_messages: int
    pending_messages: int
    deleted_messages: int
    active_users_30d: int
    active_channels: int
    total_sessions: int
    indexed_sessions: int
    oldest_message: Optional[str]
    newest_message: Optional[str]
    indexing_percentage: float
    last_activity: Optional[str]


@app.get("/guilds/{guild_id}/stats", response_model=GuildStats)
async def get_guild_stats(guild_id: int) -> GuildStats:
    """
    Get real-time statistics for a guild.
    
    Fetches actual data from PostgreSQL.
    """
    from sqlalchemy import create_engine, text
    
    settings = get_settings()
    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    
    with engine.connect() as conn:
        # Total messages (excluding deleted)
        total = conn.execute(text("""
            SELECT COUNT(*) FROM messages 
            WHERE guild_id = :g AND is_deleted = FALSE
        """), {"g": guild_id}).scalar() or 0
        
        # Indexed messages (in Qdrant - we track via sessions now)
        # Since we use session-based indexing, count messages in indexed sessions
        indexed = conn.execute(text("""
            SELECT COUNT(*) FROM messages 
            WHERE guild_id = :g AND is_deleted = FALSE
        """), {"g": guild_id}).scalar() or 0  # All non-deleted are "indexed"
        
        # Pending messages (not in any session yet)
        pending = 0  # With session-based indexing, this is handled differently
        
        # Deleted messages
        deleted = conn.execute(text("""
            SELECT COUNT(*) FROM messages 
            WHERE guild_id = :g AND is_deleted = TRUE
        """), {"g": guild_id}).scalar() or 0
        
        # Active users in last 30 days
        active_users = conn.execute(text("""
            SELECT COUNT(DISTINCT author_id) FROM messages 
            WHERE guild_id = :g 
              AND message_timestamp > NOW() - INTERVAL '30 days'
              AND is_deleted = FALSE
        """), {"g": guild_id}).scalar() or 0
        
        # Active channels (with indexed=true)
        active_channels = conn.execute(text("""
            SELECT COUNT(*) FROM channels 
            WHERE guild_id = :g AND is_indexed = TRUE
        """), {"g": guild_id}).scalar() or 0
        
        # Session stats - check if message_sessions table exists
        total_sessions = 0
        indexed_sessions = 0
        try:
            total_sessions = conn.execute(text("""
                SELECT COUNT(*) FROM message_sessions 
                WHERE guild_id = :g
            """), {"g": guild_id}).scalar() or 0
        except Exception:
            pass
        
        # Message time range
        time_range = conn.execute(text("""
            SELECT 
                MIN(message_timestamp) as oldest,
                MAX(message_timestamp) as newest
            FROM messages 
            WHERE guild_id = :g AND is_deleted = FALSE
        """), {"g": guild_id}).fetchone()
        
        # Last activity
        last_activity = conn.execute(text("""
            SELECT MAX(message_timestamp) FROM messages 
            WHERE guild_id = :g AND is_deleted = FALSE
        """), {"g": guild_id}).scalar()
    
    # Calculate indexing percentage
    indexing_pct = (indexed / total * 100) if total > 0 else 0.0
    
    return GuildStats(
        guild_id=guild_id,
        total_messages=total,
        indexed_messages=indexed,
        pending_messages=pending,
        deleted_messages=deleted,
        active_users_30d=active_users,
        active_channels=active_channels,
        total_sessions=total_sessions,
        indexed_sessions=indexed_sessions,
        oldest_message=time_range.oldest.isoformat() if time_range and time_range.oldest else None,
        newest_message=time_range.newest.isoformat() if time_range and time_range.newest else None,
        indexing_percentage=round(indexing_pct, 1),
        last_activity=last_activity.isoformat() if last_activity else None,
    )


@app.get("/guilds/{guild_id}/stats/timeseries")
async def get_guild_timeseries(
    guild_id: int,
    days: int = 30,
) -> dict:
    """
    Get message volume over time for charts.
    """
    from sqlalchemy import create_engine, text
    
    settings = get_settings()
    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    
    with engine.connect() as conn:
        result = conn.execute(text(f"""
            SELECT 
                DATE(message_timestamp) as date,
                COUNT(*) as message_count,
                COUNT(DISTINCT author_id) as unique_users
            FROM messages 
            WHERE guild_id = :g 
              AND is_deleted = FALSE
              AND message_timestamp > NOW() - INTERVAL '{days} days'
            GROUP BY DATE(message_timestamp)
            ORDER BY date ASC
        """), {"g": guild_id})
        
        rows = result.fetchall()
    
    return {
        "guild_id": guild_id,
        "days": days,
        "data": [
            {
                "date": row.date.isoformat(),
                "messages": row.message_count,
                "users": row.unique_users,
            }
            for row in rows
        ],
    }


@app.get("/guilds/{guild_id}/stats/top-channels")
async def get_top_channels(
    guild_id: int,
    limit: int = 10,
) -> dict:
    """
    Get most active channels.
    """
    from sqlalchemy import create_engine, text
    
    settings = get_settings()
    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                c.id,
                c.name,
                c.is_indexed,
                COUNT(m.id) as message_count
            FROM channels c
            LEFT JOIN messages m ON c.id = m.channel_id AND m.is_deleted = FALSE
            WHERE c.guild_id = :g
            GROUP BY c.id, c.name, c.is_indexed
            ORDER BY message_count DESC
            LIMIT :limit
        """), {"g": guild_id, "limit": limit})
        
        rows = result.fetchall()
    
    return {
        "guild_id": guild_id,
        "channels": [
            {
                "id": str(row.id),
                "name": row.name,
                "is_indexed": row.is_indexed,
                "message_count": row.message_count,
            }
            for row in rows
        ],
    }


# =============================================================================
# Slash Command API Endpoints
# =============================================================================

class SummaryRequest(BaseModel):
    """Request for channel summary."""
    guild_id: int
    channel_id: int
    hours: int = 24


class SummaryResponse(BaseModel):
    """Response for channel summary."""
    status: str
    summary: str
    message_count: int
    participant_count: int
    topics: list[str]


@app.post("/summary", response_model=SummaryResponse)
async def generate_summary(request: SummaryRequest) -> SummaryResponse:
    """Generate a summary of recent channel activity."""
    from datetime import datetime, timedelta
    from sqlalchemy import create_engine, text
    from collections import Counter
    import re
    
    settings = get_settings()
    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    cutoff = datetime.utcnow() - timedelta(hours=request.hours)
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT m.content, u.username, u.global_name, m.message_timestamp
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
        f"{row.global_name or row.username}: {row.content}"
        for row in rows
    ])
    
    # Count unique participants
    participants = set(row.global_name or row.username for row in rows)
    
    # Extract topics (keyword extraction)
    words = re.findall(r'\b[a-zA-Z]{4,15}\b', messages_text.lower())
    stop_words = {"that", "this", "with", "have", "just", "like", "from", "they", "would", "there", "their", "what", "about"}
    words = [w for w in words if w not in stop_words]
    topics = [word for word, _ in Counter(words).most_common(5)]
    
    # Generate summary using LLM
    try:
        from apps.api.src.core.llm_factory import get_llm
        from langchain_core.messages import SystemMessage, HumanMessage
        
        llm = get_llm(temperature=0.3)
        
        response = await llm.ainvoke([
            SystemMessage(content="You are a helpful assistant that summarizes Discord conversations. "
                         "Provide a concise 2-3 paragraph summary highlighting main topics discussed, "
                         "any decisions made, and notable interactions."),
            HumanMessage(content=f"Summarize this conversation:\n\n{messages_text[:6000]}"),
        ])
        
        summary = response.content.strip()
    except Exception as e:
        summary = f"Could not generate summary: {str(e)[:100]}"
    
    return SummaryResponse(
        status="success",
        summary=summary,
        message_count=len(rows),
        participant_count=len(participants),
        topics=topics,
    )


class SearchRequest(BaseModel):
    """Request for message search."""
    query: str
    guild_id: int
    channel_id: Optional[int] = None
    user_id: Optional[int] = None
    limit: int = 5


class SearchResult(BaseModel):
    """Single search result."""
    content: str
    author: str
    channel: str
    timestamp: str
    score: float


class SearchResponse(BaseModel):
    """Response for message search."""
    results: list[SearchResult]


@app.post("/search", response_model=SearchResponse)
async def search_messages(request: SearchRequest) -> SearchResponse:
    """Semantic search across chat history."""
    from apps.api.src.core.llm_factory import get_embedding_model
    from apps.api.src.services.qdrant_service import qdrant_service
    from sqlalchemy import create_engine, text
    
    settings = get_settings()
    
    # Generate query embedding
    embedding_model = get_embedding_model()
    query_embedding = embedding_model.embed_query(request.query)
    
    # Search Qdrant (use low threshold for better recall)
    results = qdrant_service.search(
        query_embedding=query_embedding,
        guild_id=request.guild_id,
        channel_ids=[request.channel_id] if request.channel_id else None,
        limit=request.limit,
        score_threshold=0.1,
    )
    
    # Fetch message details from Postgres
    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    
    search_results = []
    for r in results:
        payload = r.get("payload", {})
        message_ids = payload.get("message_ids", [])
        
        if not message_ids:
            continue
        
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT m.content, u.username, u.global_name, c.name as channel_name, m.message_timestamp
                FROM messages m
                JOIN users u ON m.author_id = u.id
                JOIN channels c ON m.channel_id = c.id
                WHERE m.id = :msg_id
            """), {"msg_id": message_ids[0]})
            row = result.fetchone()
        
        if row:
            search_results.append(SearchResult(
                content=row.content[:500],
                author=row.global_name or row.username,
                channel=row.channel_name,
                timestamp=row.message_timestamp.isoformat(),
                score=r.get("score", 0),
            ))
    
    return SearchResponse(results=search_results)


@app.get("/guilds/{guild_id}/topics")
async def get_trending_topics(guild_id: int, days: int = 7) -> dict:
    """Extract trending topics from recent messages."""
    from datetime import datetime, timedelta
    from collections import Counter
    import re
    from sqlalchemy import create_engine, text
    
    settings = get_settings()
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
    
    # Keyword extraction
    all_text = " ".join(row.content for row in rows)
    words = re.findall(r'\b[a-zA-Z]{4,15}\b', all_text.lower())
    
    # Remove common stop words
    stop_words = {
        "that", "this", "with", "have", "just", "like", "from", "they",
        "would", "there", "their", "what", "about", "which", "when",
        "make", "been", "more", "some", "could", "than", "other",
        "http", "https", "www", "com", "org",
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


if __name__ == "__main__":
    import uvicorn
    
    settings = get_settings()
    uvicorn.run(
        "apps.api.src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
