/**
 * Discord API types and permission constants for RBAC
 */

export interface DiscordGuild {
  id: string;
  name: string;
  icon: string | null;
  owner: boolean;
  permissions: string; // Bitfield as string (can exceed JS safe integer)
  features: string[];
}

/**
 * Discord permission flags as BigInt values.
 * Full list: https://discord.com/developers/docs/topics/permissions
 */
export const DiscordPermissions = {
  ADMINISTRATOR: BigInt(0x8),
  MANAGE_GUILD: BigInt(0x20),
  MANAGE_CHANNELS: BigInt(0x10),
  MANAGE_ROLES: BigInt(0x10000000),
  VIEW_AUDIT_LOG: BigInt(0x80),
  KICK_MEMBERS: BigInt(0x2),
  BAN_MEMBERS: BigInt(0x4),
} as const;
