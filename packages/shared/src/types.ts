/**
 * Shared TypeScript interfaces for Discord Community Intelligence System.
 * These mirror the Pydantic models in Python packages.
 */

// =============================================================================
// Core Discord Entities
// =============================================================================

export interface Guild {
  id: string; // Discord snowflake as string for JS BigInt safety
  name: string;
  iconHash: string | null;
  ownerId: string;
  isActive: boolean;
  premiumTier: number;
  joinedAt: string; // ISO datetime
  createdAt: string;
  updatedAt: string;
}

export interface Channel {
  id: string;
  guildId: string;
  name: string;
  type: ChannelType;
  isIndexed: boolean; // Control Plane flag
  isDeleted: boolean;
  createdAt: string;
  updatedAt: string;
}

export enum ChannelType {
  TEXT = 0,
  DM = 1,
  VOICE = 2,
  GROUP_DM = 3,
  CATEGORY = 4,
  NEWS = 5,
  FORUM = 15,
}

export interface Message {
  id: string;
  channelId: string;
  guildId: string;
  authorId: string;
  content: string;
  replyToId: string | null;
  threadId: string | null;
  attachmentCount: number;
  embedCount: number;
  mentionCount: number;
  qdrantPointId: string | null;
  indexedAt: string | null;
  isDeleted: boolean;
  deletedAt: string | null;
  messageTimestamp: string;
  createdAt: string;
  updatedAt: string;
}

export interface User {
  id: string;
  username: string;
  discriminator: string | null;
  globalName: string | null;
  avatarHash: string | null;
  firstSeenAt: string;
  updatedAt: string;
}

export interface GuildMember {
  guildId: string;
  userId: string;
  nickname: string | null;
  joinedAt: string | null;
  messageCount: number;
  lastMessageAt: string | null;
}

// =============================================================================
// API Request/Response Types
// =============================================================================

export interface AskQuery {
  guildId: string;
  query: string;
  channelIds?: string[]; // Optional filter to specific channels
}

export interface AskResponse {
  answer: string;
  sources: MessageSource[];
  routedTo: RouterIntent;
  executionTimeMs: number;
}

export interface MessageSource {
  messageId: string;
  channelId: string;
  authorId: string;
  content: string;
  timestamp: string;
  relevanceScore: number;
}

export enum RouterIntent {
  ANALYTICS_DB = "analytics_db",
  VECTOR_RAG = "vector_rag",
  WEB_SEARCH = "web_search",
  GENERAL_KNOWLEDGE = "general_knowledge",
}

// =============================================================================
// Control Plane Types (for Next.js Dashboard)
// =============================================================================

export interface ChannelIndexConfig {
  channelId: string;
  channelName: string;
  isIndexed: boolean;
  messageCount: number;
  lastIndexedAt: string | null;
}

export interface GuildDashboard {
  guild: Guild;
  channels: ChannelIndexConfig[];
  stats: GuildStats;
}

export interface GuildStats {
  totalMessages: number;
  indexedMessages: number;
  activeUsers: number;
  topContributors: TopContributor[];
}

export interface TopContributor {
  userId: string;
  username: string;
  messageCount: number;
}

// =============================================================================
// Celery Task Types
// =============================================================================

export interface IndexTaskPayload {
  guildId: string;
  channelId: string;
  messageIds: string[];
}

export interface DeleteTaskPayload {
  guildId: string;
  messageId: string;
  qdrantPointId: string;
}
