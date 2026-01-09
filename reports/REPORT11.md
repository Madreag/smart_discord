# REPORT 11: Real Analytics Data in Dashboard

> **Priority**: P1 (High)  
> **Effort**: Medium (4-6 hours)  
> **Status**: Not Implemented (hardcoded placeholders)

---

## 1. Executive Summary

The web dashboard at `apps/web/src/app/dashboard/[guildId]/page.tsx` displays **hardcoded placeholder values** for server statistics. Users see fake data that doesn't reflect actual usage.

**Current State**:
```typescript
// Hardcoded values - NOT real data
<StatCard title="Total Messages" value="12,847" />
<StatCard title="Indexed Messages" value="8,234" />
<StatCard title="Active Users (30d)" value="156" />
```

**Target State**: Real-time stats fetched from PostgreSQL via the API.

---

## 2. Current Implementation Analysis

### What Exists

```typescript
// apps/web/src/app/dashboard/[guildId]/page.tsx (current)
export default async function GuildPage({ params }: GuildPageProps) {
  // ... auth check ...
  
  return (
    <main>
      {/* Statistics - HARDCODED */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        <StatCard title="Total Messages" value="12,847" />
        <StatCard title="Indexed Messages" value="8,234" />
        <StatCard title="Active Users (30d)" value="156" />
      </div>
      {/* ... */}
    </main>
  );
}
```

### The Problem

1. Statistics are hardcoded strings, not fetched from backend
2. No API endpoint exists to retrieve guild statistics
3. Dashboard doesn't reflect actual bot activity
4. Admins can't verify indexing progress

---

## 3. Implementation Guide

### Step 1: Create API Endpoint

```python
# apps/api/src/main.py (add new endpoint)

from datetime import datetime, timedelta
from pydantic import BaseModel


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
    oldest_message: str | None
    newest_message: str | None
    indexing_percentage: float
    last_activity: str | None


@app.get("/guilds/{guild_id}/stats", response_model=GuildStats)
async def get_guild_stats(guild_id: int) -> GuildStats:
    """
    Get real-time statistics for a guild.
    
    Fetches actual data from PostgreSQL.
    """
    from sqlalchemy import create_engine, text
    from apps.api.src.core.config import get_settings
    
    settings = get_settings()
    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    
    with engine.connect() as conn:
        # Total messages (excluding deleted)
        total = conn.execute(text("""
            SELECT COUNT(*) FROM messages 
            WHERE guild_id = :g AND is_deleted = FALSE
        """), {"g": guild_id}).scalar() or 0
        
        # Indexed messages (have qdrant_point_id)
        indexed = conn.execute(text("""
            SELECT COUNT(*) FROM messages 
            WHERE guild_id = :g AND qdrant_point_id IS NOT NULL
        """), {"g": guild_id}).scalar() or 0
        
        # Pending messages (not indexed yet)
        pending = conn.execute(text("""
            SELECT COUNT(*) FROM messages m
            JOIN channels c ON m.channel_id = c.id
            WHERE m.guild_id = :g 
              AND m.is_deleted = FALSE 
              AND m.qdrant_point_id IS NULL
              AND c.is_indexed = TRUE
        """), {"g": guild_id}).scalar() or 0
        
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
        
        # Session stats
        total_sessions = conn.execute(text("""
            SELECT COUNT(*) FROM message_sessions 
            WHERE guild_id = :g
        """), {"g": guild_id}).scalar() or 0
        
        indexed_sessions = conn.execute(text("""
            SELECT COUNT(*) FROM message_sessions 
            WHERE guild_id = :g AND qdrant_point_id IS NOT NULL
        """), {"g": guild_id}).scalar() or 0
        
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
    from apps.api.src.core.config import get_settings
    
    settings = get_settings()
    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                DATE(message_timestamp) as date,
                COUNT(*) as message_count,
                COUNT(DISTINCT author_id) as unique_users
            FROM messages 
            WHERE guild_id = :g 
              AND is_deleted = FALSE
              AND message_timestamp > NOW() - INTERVAL ':days days'
            GROUP BY DATE(message_timestamp)
            ORDER BY date ASC
        """.replace(":days", str(days))), {"g": guild_id})
        
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
    from apps.api.src.core.config import get_settings
    
    settings = get_settings()
    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                c.id,
                c.name,
                c.is_indexed,
                COUNT(m.id) as message_count,
                COUNT(CASE WHEN m.qdrant_point_id IS NOT NULL THEN 1 END) as indexed_count
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
                "indexed_count": row.indexed_count,
            }
            for row in rows
        ],
    }
```

### Step 2: TypeScript Types

```typescript
// apps/web/src/types/stats.ts

export interface GuildStats {
  guild_id: number;
  total_messages: number;
  indexed_messages: number;
  pending_messages: number;
  deleted_messages: number;
  active_users_30d: number;
  active_channels: number;
  total_sessions: number;
  indexed_sessions: number;
  oldest_message: string | null;
  newest_message: string | null;
  indexing_percentage: number;
  last_activity: string | null;
}

export interface TimeseriesDataPoint {
  date: string;
  messages: number;
  users: number;
}

export interface ChannelStats {
  id: string;
  name: string;
  is_indexed: boolean;
  message_count: number;
  indexed_count: number;
}
```

### Step 3: API Client Function

```typescript
// apps/web/src/lib/api.ts

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function getGuildStats(guildId: string): Promise<GuildStats> {
  const response = await fetch(`${API_URL}/guilds/${guildId}/stats`, {
    next: { revalidate: 60 }, // Cache for 60 seconds
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch stats: ${response.status}`);
  }

  return response.json();
}

export async function getGuildTimeseries(
  guildId: string,
  days: number = 30
): Promise<{ data: TimeseriesDataPoint[] }> {
  const response = await fetch(
    `${API_URL}/guilds/${guildId}/stats/timeseries?days=${days}`,
    { next: { revalidate: 300 } } // Cache for 5 minutes
  );

  if (!response.ok) {
    throw new Error(`Failed to fetch timeseries: ${response.status}`);
  }

  return response.json();
}

export async function getTopChannels(
  guildId: string,
  limit: number = 10
): Promise<{ channels: ChannelStats[] }> {
  const response = await fetch(
    `${API_URL}/guilds/${guildId}/stats/top-channels?limit=${limit}`,
    { next: { revalidate: 300 } }
  );

  if (!response.ok) {
    throw new Error(`Failed to fetch channels: ${response.status}`);
  }

  return response.json();
}
```

### Step 4: Updated Dashboard Page

```typescript
// apps/web/src/app/dashboard/[guildId]/page.tsx

import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { getGuildStats, getGuildTimeseries, getTopChannels } from "@/lib/api";
import { StatsCard } from "@/components/stats-card";
import { ActivityChart } from "@/components/activity-chart";
import { ChannelList } from "@/components/channel-list";
import { IndexingProgress } from "@/components/indexing-progress";

interface GuildPageProps {
  params: Promise<{ guildId: string }>;
}

export default async function GuildPage({ params }: GuildPageProps) {
  const session = await auth();
  if (!session) {
    redirect("/login");
  }

  const { guildId } = await params;

  // Fetch real data from API
  let stats;
  let timeseries;
  let topChannels;

  try {
    [stats, timeseries, topChannels] = await Promise.all([
      getGuildStats(guildId),
      getGuildTimeseries(guildId, 30),
      getTopChannels(guildId, 5),
    ]);
  } catch (error) {
    console.error("Failed to fetch guild data:", error);
    // Show error state
    return (
      <main className="min-h-screen bg-discord-darkest p-8">
        <div className="bg-red-500/10 border border-red-500 rounded-lg p-4">
          <p className="text-red-400">
            Failed to load statistics. Please ensure the API is running.
          </p>
        </div>
      </main>
    );
  }

  // Format numbers with commas
  const formatNumber = (n: number) => n.toLocaleString();

  return (
    <main className="min-h-screen bg-discord-darkest">
      <header className="bg-discord-darker border-b border-gray-800 px-6 py-4">
        <h1 className="text-xl font-bold text-white">Server Dashboard</h1>
        {stats.last_activity && (
          <p className="text-sm text-gray-400">
            Last activity: {new Date(stats.last_activity).toLocaleString()}
          </p>
        )}
      </header>

      <div className="p-6 space-y-6">
        {/* Main Statistics */}
        <section>
          <h2 className="text-lg font-semibold text-white mb-4">Overview</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <StatsCard
              title="Total Messages"
              value={formatNumber(stats.total_messages)}
              subtitle={`Since ${stats.oldest_message ? new Date(stats.oldest_message).toLocaleDateString() : "N/A"}`}
            />
            <StatsCard
              title="Indexed Messages"
              value={formatNumber(stats.indexed_messages)}
              subtitle={`${stats.indexing_percentage}% indexed`}
              trend={stats.indexing_percentage >= 90 ? "up" : "neutral"}
            />
            <StatsCard
              title="Active Users"
              value={formatNumber(stats.active_users_30d)}
              subtitle="Last 30 days"
            />
            <StatsCard
              title="Active Channels"
              value={formatNumber(stats.active_channels)}
              subtitle="Indexing enabled"
            />
          </div>
        </section>

        {/* Indexing Progress */}
        <section>
          <h2 className="text-lg font-semibold text-white mb-4">
            Indexing Status
          </h2>
          <IndexingProgress
            indexed={stats.indexed_messages}
            pending={stats.pending_messages}
            total={stats.total_messages}
            sessions={{
              indexed: stats.indexed_sessions,
              total: stats.total_sessions,
            }}
          />
        </section>

        {/* Activity Chart */}
        <section>
          <h2 className="text-lg font-semibold text-white mb-4">
            Activity (Last 30 Days)
          </h2>
          <ActivityChart data={timeseries.data} />
        </section>

        {/* Top Channels */}
        <section>
          <h2 className="text-lg font-semibold text-white mb-4">
            Most Active Channels
          </h2>
          <ChannelList channels={topChannels.channels} />
        </section>
      </div>
    </main>
  );
}
```

### Step 5: React Components

```typescript
// apps/web/src/components/stats-card.tsx
"use client";

import { TrendingUp, TrendingDown, Minus } from "lucide-react";

interface StatsCardProps {
  title: string;
  value: string;
  subtitle?: string;
  trend?: "up" | "down" | "neutral";
}

export function StatsCard({ title, value, subtitle, trend }: StatsCardProps) {
  const TrendIcon = trend === "up" ? TrendingUp : trend === "down" ? TrendingDown : Minus;
  const trendColor = trend === "up" ? "text-green-400" : trend === "down" ? "text-red-400" : "text-gray-400";

  return (
    <div className="bg-discord-darker rounded-lg p-4 border border-gray-800">
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-400">{title}</p>
        {trend && <TrendIcon className={`w-4 h-4 ${trendColor}`} />}
      </div>
      <p className="text-2xl font-bold text-white mt-1">{value}</p>
      {subtitle && <p className="text-xs text-gray-500 mt-1">{subtitle}</p>}
    </div>
  );
}


// apps/web/src/components/indexing-progress.tsx
"use client";

interface IndexingProgressProps {
  indexed: number;
  pending: number;
  total: number;
  sessions: { indexed: number; total: number };
}

export function IndexingProgress({ indexed, pending, total, sessions }: IndexingProgressProps) {
  const percentage = total > 0 ? (indexed / total) * 100 : 0;
  const sessionPercentage = sessions.total > 0 ? (sessions.indexed / sessions.total) * 100 : 0;

  return (
    <div className="bg-discord-darker rounded-lg p-4 border border-gray-800 space-y-4">
      {/* Messages Progress */}
      <div>
        <div className="flex justify-between text-sm mb-2">
          <span className="text-gray-400">Messages</span>
          <span className="text-white">{indexed.toLocaleString()} / {total.toLocaleString()}</span>
        </div>
        <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-discord-blurple transition-all duration-500"
            style={{ width: `${percentage}%` }}
          />
        </div>
        {pending > 0 && (
          <p className="text-xs text-yellow-400 mt-1">
            {pending.toLocaleString()} messages pending indexing
          </p>
        )}
      </div>

      {/* Sessions Progress */}
      <div>
        <div className="flex justify-between text-sm mb-2">
          <span className="text-gray-400">Sessions</span>
          <span className="text-white">{sessions.indexed.toLocaleString()} / {sessions.total.toLocaleString()}</span>
        </div>
        <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-green-500 transition-all duration-500"
            style={{ width: `${sessionPercentage}%` }}
          />
        </div>
      </div>
    </div>
  );
}


// apps/web/src/components/activity-chart.tsx
"use client";

import { useMemo } from "react";

interface DataPoint {
  date: string;
  messages: number;
  users: number;
}

interface ActivityChartProps {
  data: DataPoint[];
}

export function ActivityChart({ data }: ActivityChartProps) {
  const maxMessages = useMemo(() => Math.max(...data.map(d => d.messages), 1), [data]);

  if (data.length === 0) {
    return (
      <div className="bg-discord-darker rounded-lg p-8 border border-gray-800 text-center">
        <p className="text-gray-400">No activity data available</p>
      </div>
    );
  }

  return (
    <div className="bg-discord-darker rounded-lg p-4 border border-gray-800">
      <div className="flex items-end gap-1 h-32">
        {data.map((point, i) => (
          <div
            key={point.date}
            className="flex-1 bg-discord-blurple/80 hover:bg-discord-blurple rounded-t transition-colors cursor-pointer group relative"
            style={{ height: `${(point.messages / maxMessages) * 100}%`, minHeight: "4px" }}
            title={`${point.date}: ${point.messages} messages, ${point.users} users`}
          >
            <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 bg-gray-900 text-white text-xs px-2 py-1 rounded opacity-0 group-hover:opacity-100 whitespace-nowrap z-10">
              {point.messages} msgs
            </div>
          </div>
        ))}
      </div>
      <div className="flex justify-between mt-2 text-xs text-gray-500">
        <span>{data[0]?.date}</span>
        <span>{data[data.length - 1]?.date}</span>
      </div>
    </div>
  );
}
```

---

## 4. Caching Strategy

For performance, cache stats at multiple levels:

```python
# apps/api/src/services/stats_service.py

from functools import lru_cache
from datetime import datetime, timedelta
import redis

# Redis for distributed caching
redis_client = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))

CACHE_TTL = 60  # 1 minute


async def get_cached_stats(guild_id: int) -> dict | None:
    """Get stats from cache."""
    key = f"guild_stats:{guild_id}"
    data = redis_client.get(key)
    if data:
        import json
        return json.loads(data)
    return None


async def set_cached_stats(guild_id: int, stats: dict) -> None:
    """Cache stats."""
    import json
    key = f"guild_stats:{guild_id}"
    redis_client.setex(key, CACHE_TTL, json.dumps(stats))
```

---

## 5. References

- [Next.js Data Fetching](https://nextjs.org/docs/app/building-your-application/data-fetching)
- [React Server Components](https://react.dev/reference/rsc/server-components)
- [Recharts (for charts)](https://recharts.org/)

---

## 6. Checklist

- [ ] Add `/guilds/{guild_id}/stats` endpoint to API
- [ ] Add `/guilds/{guild_id}/stats/timeseries` endpoint
- [ ] Add `/guilds/{guild_id}/stats/top-channels` endpoint
- [ ] Create TypeScript types in `apps/web/src/types/stats.ts`
- [ ] Create API client in `apps/web/src/lib/api.ts`
- [ ] Create `StatsCard` component
- [ ] Create `IndexingProgress` component
- [ ] Create `ActivityChart` component
- [ ] Update `apps/web/src/app/dashboard/[guildId]/page.tsx`
- [ ] Add Redis caching for stats
- [ ] Test with real guild data
