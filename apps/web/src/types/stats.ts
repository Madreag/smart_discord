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

export interface TimeseriesResponse {
  guild_id: number;
  days: number;
  data: TimeseriesDataPoint[];
}

export interface ChannelStats {
  id: string;
  name: string;
  is_indexed: boolean;
  message_count: number;
}

export interface TopChannelsResponse {
  guild_id: number;
  channels: ChannelStats[];
}
