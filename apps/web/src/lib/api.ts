import type { GuildStats, TimeseriesResponse, TopChannelsResponse } from "@/types/stats";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function getGuildStats(guildId: string): Promise<GuildStats> {
  const response = await fetch(`${API_URL}/guilds/${guildId}/stats`, {
    next: { revalidate: 60 },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch stats: ${response.status}`);
  }

  return response.json();
}

export async function getGuildTimeseries(
  guildId: string,
  days: number = 30
): Promise<TimeseriesResponse> {
  const response = await fetch(
    `${API_URL}/guilds/${guildId}/stats/timeseries?days=${days}`,
    { next: { revalidate: 300 } }
  );

  if (!response.ok) {
    throw new Error(`Failed to fetch timeseries: ${response.status}`);
  }

  return response.json();
}

export async function getTopChannels(
  guildId: string,
  limit: number = 10
): Promise<TopChannelsResponse> {
  const response = await fetch(
    `${API_URL}/guilds/${guildId}/stats/top-channels?limit=${limit}`,
    { next: { revalidate: 300 } }
  );

  if (!response.ok) {
    throw new Error(`Failed to fetch channels: ${response.status}`);
  }

  return response.json();
}
