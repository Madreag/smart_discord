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
    
    # TODO: Initialize database connections, Qdrant client, etc.
    
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
    try:
        # Step 1: Classify intent
        intent = await classify_intent(query.query)
        
        # Step 2: Route to appropriate agent
        if intent == RouterIntent.ANALYTICS_DB:
            response = await process_analytics_query(
                query=query.query,
                guild_id=query.guild_id,
            )
        elif intent == RouterIntent.VECTOR_RAG:
            response = await process_rag_query(
                query=query.query,
                guild_id=query.guild_id,
                channel_ids=query.channel_ids,
            )
        elif intent == RouterIntent.WEB_SEARCH:
            response = await process_web_search_query(
                query=query.query,
                guild_id=query.guild_id,
            )
        elif intent == RouterIntent.GENERAL_KNOWLEDGE:
            response = await process_general_knowledge_query(
                query=query.query,
                guild_id=query.guild_id,
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Unknown intent: {intent}",
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


class ProviderInfoResponse(BaseModel):
    """Current LLM provider configuration."""
    llm_provider: str
    llm_model: str
    embedding_provider: str
    embedding_model: str
    has_api_key: bool
    available_providers: list[str]


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
            
            # Filter to text channels (type 0) and format response
            text_channels = [
                ChannelResponse(
                    id=str(ch["id"]),
                    name=ch["name"],
                    type=ch["type"],
                    isIndexed=False,  # TODO: Check database for indexed status
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


if __name__ == "__main__":
    import uvicorn
    
    settings = get_settings()
    uvicorn.run(
        "apps.api.src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
