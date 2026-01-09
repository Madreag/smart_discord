import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import Link from "next/link";
import { filterManageableGuilds } from "@/lib/permissions";
import type { DiscordGuild } from "@/types/discord";

async function getUserGuilds(accessToken: string): Promise<DiscordGuild[]> {
  try {
    const response = await fetch("https://discord.com/api/users/@me/guilds", {
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
      next: { revalidate: 60 }, // Cache for 60 seconds to reduce API calls
    });
    
    if (!response.ok) {
      console.error(`Discord API error: ${response.status}`);
      return [];
    }
    
    const guilds: DiscordGuild[] = await response.json();
    
    // RBAC: Filter to only guilds user can manage (ADMINISTRATOR or MANAGE_GUILD)
    return filterManageableGuilds(guilds);
  } catch (error) {
    console.error("Failed to fetch guilds:", error);
    return [];
  }
}

export default async function DashboardPage() {
  const session = await auth();

  if (!session) {
    redirect("/login");
  }

  const guilds = await getUserGuilds(session.accessToken);

  return (
    <main className="min-h-screen bg-discord-darkest">
      {/* Header */}
      <header className="bg-discord-darker border-b border-gray-800">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <h1 className="text-xl font-bold text-white">
            Discord Community Intelligence
          </h1>
          <div className="flex items-center gap-4">
            <a
              href="/dashboard/settings"
              className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
            >
              Settings
            </a>
            <Link
              href="/api/auth/signout"
              className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
            >
              Sign Out
            </Link>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-4 py-8">
        <h2 className="text-2xl font-bold text-white mb-6">Your Servers</h2>
        
        {guilds.length === 0 ? (
          <div className="bg-discord-darker rounded-lg p-8 text-center">
            <p className="text-gray-400">
              No servers found. Make sure the bot is added to your servers.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {guilds.map((guild) => (
              <a
                key={guild.id}
                href={`/dashboard/${guild.id}`}
                className="bg-discord-darker rounded-lg p-4 hover:bg-discord-dark transition-colors flex items-center gap-4"
              >
                {guild.icon ? (
                  <img
                    src={`https://cdn.discordapp.com/icons/${guild.id}/${guild.icon}.png`}
                    alt={guild.name}
                    className="w-12 h-12 rounded-full"
                  />
                ) : (
                  <div className="w-12 h-12 rounded-full bg-discord-blurple flex items-center justify-center text-white font-bold">
                    {[...guild.name][0] || "?"}
                  </div>
                )}
                <div>
                  <h3 className="text-white font-semibold">{guild.name}</h3>
                  <p className="text-sm text-gray-400">Click to manage</p>
                </div>
              </a>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
