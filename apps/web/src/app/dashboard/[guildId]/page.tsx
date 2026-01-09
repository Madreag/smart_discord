import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { ChannelToggle } from "@/components/ChannelToggle";
import { PrePromptEditor } from "@/components/PrePromptEditor";
import { canManageGuildById } from "@/lib/permissions";
import type { DiscordGuild } from "@/types/discord";
import { getGuildStats, getGuildTimeseries, getTopChannels } from "@/lib/api";
import { StatsCard } from "@/components/stats-card";
import { IndexingProgress } from "@/components/indexing-progress";
import { ActivityChart } from "@/components/activity-chart";
import { ChannelList } from "@/components/channel-list";

interface Channel {
  id: string;
  name: string;
  type: number;
  isIndexed: boolean;
}

interface GuildPageProps {
  params: Promise<{ guildId: string }>;
}

interface ChannelsResult {
  channels: Channel[];
  error?: string;
}

async function getUserGuilds(accessToken: string): Promise<DiscordGuild[]> {
  try {
    const response = await fetch("https://discord.com/api/users/@me/guilds", {
      headers: { Authorization: `Bearer ${accessToken}` },
      next: { revalidate: 60 },
    });
    if (!response.ok) return [];
    return response.json();
  } catch {
    return [];
  }
}

async function getGuildChannels(guildId: string): Promise<ChannelsResult> {
  try {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const response = await fetch(`${apiUrl}/guilds/${guildId}/channels`, {
      cache: "no-store",
    });
    
    if (response.status === 403) {
      return { 
        channels: [], 
        error: "Bot not in this server. Please invite the bot first." 
      };
    }
    
    if (!response.ok) {
      return { channels: [], error: `Failed to fetch channels (${response.status})` };
    }
    
    const channels = await response.json();
    return { channels };
  } catch (error) {
    return { channels: [], error: "Could not connect to API server" };
  }
}

export default async function GuildPage({ params }: GuildPageProps) {
  const session = await auth();

  if (!session) {
    redirect("/login");
  }

  const { guildId } = await params;

  // RBAC: Server-side permission validation
  const guilds = await getUserGuilds(session.accessToken);
  const hasAccess = canManageGuildById(guilds, guildId);

  if (!hasAccess) {
    // User doesn't have permission - redirect with error
    redirect("/dashboard?error=unauthorized");
  }

  const { channels, error } = await getGuildChannels(guildId);

  // Fetch real analytics data
  let stats = null;
  let timeseries = null;
  let topChannels = null;
  let statsError = null;

  try {
    [stats, timeseries, topChannels] = await Promise.all([
      getGuildStats(guildId),
      getGuildTimeseries(guildId, 30),
      getTopChannels(guildId, 5),
    ]);
  } catch (e) {
    statsError = "Could not load analytics data";
  }

  const formatNumber = (n: number) => n.toLocaleString();

  return (
    <main className="min-h-screen bg-discord-darkest">
      {/* Header */}
      <header className="bg-discord-darker border-b border-gray-800">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <a
              href="/dashboard"
              className="text-gray-400 hover:text-white transition-colors"
            >
              ← Back
            </a>
            <h1 className="text-xl font-bold text-white">Channel Management</h1>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-4 py-8">
        {error && (
          <div className="bg-yellow-900/20 border border-yellow-500/30 rounded-lg p-4 mb-6">
            <p className="text-yellow-400">{error}</p>
            <p className="text-sm text-gray-400 mt-2">
              Invite the bot to this server using the Discord Developer Portal, then refresh.
            </p>
          </div>
        )}

        {/* Pre-Prompt Editor */}
        <div className="mb-6">
          <PrePromptEditor guildId={guildId} />
        </div>
        
        <div className="bg-discord-darker rounded-lg overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-800">
            <h2 className="text-lg font-semibold text-white">
              Channel Indexing Settings
            </h2>
            <p className="text-sm text-gray-400 mt-1">
              Toggle which channels should be indexed for AI search
            </p>
          </div>

          <div className="divide-y divide-gray-800">
            {channels.length === 0 && !error && (
              <div className="px-6 py-8 text-center text-gray-400">
                No text channels found in this server.
              </div>
            )}
            {channels.map((channel) => (
              <ChannelToggle
                key={channel.id}
                channelId={channel.id}
                channelName={channel.name}
                guildId={guildId}
                initialIndexed={channel.isIndexed}
              />
            ))}
          </div>
        </div>

        {/* Stats Section */}
        {statsError ? (
          <div className="mt-8 bg-yellow-900/20 border border-yellow-500/30 rounded-lg p-4">
            <p className="text-yellow-400">{statsError}</p>
          </div>
        ) : stats ? (
          <div className="mt-8 space-y-6">
            {/* Overview Stats */}
            <section>
              <h2 className="text-lg font-semibold text-white mb-4">Overview</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <StatsCard
                  title="Total Messages"
                  value={formatNumber(stats.total_messages)}
                  subtitle={stats.oldest_message ? `Since ${new Date(stats.oldest_message).toLocaleDateString()}` : undefined}
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
              <h2 className="text-lg font-semibold text-white mb-4">Indexing Status</h2>
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
            {timeseries && timeseries.data.length > 0 && (
              <section>
                <h2 className="text-lg font-semibold text-white mb-4">Activity (Last 30 Days)</h2>
                <ActivityChart data={timeseries.data} />
              </section>
            )}

            {/* Top Channels */}
            {topChannels && topChannels.channels.length > 0 && (
              <section>
                <h2 className="text-lg font-semibold text-white mb-4">Most Active Channels</h2>
                <ChannelList channels={topChannels.channels} />
              </section>
            )}

            {/* Last Activity */}
            {stats.last_activity && (
              <p className="text-sm text-gray-500 text-right">
                Last activity: {new Date(stats.last_activity).toLocaleString()}
              </p>
            )}
          </div>
        ) : null}
      </div>
    </main>
  );
}
