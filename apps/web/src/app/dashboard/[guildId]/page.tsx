import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { ChannelToggle } from "@/components/ChannelToggle";

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
  const { channels, error } = await getGuildChannels(guildId);

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
        <div className="mt-8 grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-discord-darker rounded-lg p-6">
            <h3 className="text-gray-400 text-sm font-medium">Total Messages</h3>
            <p className="text-3xl font-bold text-white mt-2">12,345</p>
          </div>
          <div className="bg-discord-darker rounded-lg p-6">
            <h3 className="text-gray-400 text-sm font-medium">Indexed Messages</h3>
            <p className="text-3xl font-bold text-discord-green mt-2">8,901</p>
          </div>
          <div className="bg-discord-darker rounded-lg p-6">
            <h3 className="text-gray-400 text-sm font-medium">Active Users</h3>
            <p className="text-3xl font-bold text-discord-blurple mt-2">156</p>
          </div>
        </div>
      </div>
    </main>
  );
}
