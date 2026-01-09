/**
 * Discord permission utilities for RBAC
 */

import { DiscordPermissions, DiscordGuild } from "@/types/discord";

/**
 * Check if a permission bitfield includes a specific permission.
 * Uses BigInt to handle 64-bit Discord permissions safely.
 */
export function hasPermission(
  permissionsBitfield: string,
  permission: bigint
): boolean {
  try {
    const perms = BigInt(permissionsBitfield);
    return (perms & permission) !== BigInt(0);
  } catch {
    // Invalid permissions string
    return false;
  }
}

/**
 * Check if user has permission to manage a guild.
 * Requires ADMINISTRATOR or MANAGE_GUILD permission.
 */
export function canManageGuild(permissions: string): boolean {
  return (
    hasPermission(permissions, DiscordPermissions.ADMINISTRATOR) ||
    hasPermission(permissions, DiscordPermissions.MANAGE_GUILD)
  );
}

/**
 * Filter guilds to only those the user can manage.
 */
export function filterManageableGuilds(guilds: DiscordGuild[]): DiscordGuild[] {
  return guilds.filter((guild) => {
    // Owner always has full permissions
    if (guild.owner) return true;
    // Check permission bits
    return canManageGuild(guild.permissions);
  });
}

/**
 * Check if user can manage a specific guild by ID.
 * Used for server-side validation on guild-specific pages.
 */
export function canManageGuildById(
  guilds: DiscordGuild[],
  guildId: string
): boolean {
  const guild = guilds.find((g) => g.id === guildId);
  if (!guild) return false;
  if (guild.owner) return true;
  return canManageGuild(guild.permissions);
}
