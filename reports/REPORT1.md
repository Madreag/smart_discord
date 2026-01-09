# REPORT 1: RBAC Permission Check for Discord Dashboard

> **Priority**: P0 (Critical)  
> **Effort**: 2-4 hours  
> **Status**: Not Implemented

---

## 1. Executive Summary

The web dashboard currently shows ALL Discord guilds that a user belongs to, regardless of their permissions. This is a **security vulnerability** - users can access and modify settings for servers they shouldn't manage.

**Target State**: Only show guilds where the user has `MANAGE_GUILD` (0x20) or `ADMINISTRATOR` (0x8) permission bits set.

---

## 2. Current Implementation Analysis

### What Exists

```typescript
// apps/web/src/app/dashboard/page.tsx (current)
async function getUserGuilds(accessToken: string): Promise<Guild[]> {
  const response = await fetch("https://discord.com/api/users/@me/guilds", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  return response.json();  // Returns ALL guilds - NO FILTERING
}
```

### The Problem

Discord's `/users/@me/guilds` endpoint returns a `permissions` field as a string representing a bitfield. This field is currently **ignored**.

---

## 3. Discord Permission System Deep Dive

### Permission Bitfield

Discord permissions are stored as a 64-bit integer encoded as a string. Each bit represents a specific permission:

| Permission | Bit Value | Hex | Description |
|------------|-----------|-----|-------------|
| ADMINISTRATOR | 1 << 3 | 0x8 | Full admin access |
| MANAGE_GUILD | 1 << 5 | 0x20 | Manage server settings |
| MANAGE_CHANNELS | 1 << 4 | 0x10 | Manage channels |
| KICK_MEMBERS | 1 << 1 | 0x2 | Kick users |
| BAN_MEMBERS | 1 << 2 | 0x4 | Ban users |

### API Response Structure

```json
{
  "id": "123456789",
  "name": "My Server",
  "icon": "abc123",
  "owner": false,
  "permissions": "2147483647",  // <-- This is the bitfield
  "features": ["COMMUNITY"]
}
```

### Bitwise Operations in JavaScript/TypeScript

Since Discord permissions can exceed JavaScript's safe integer limit (53 bits), we must use `BigInt`:

```typescript
// CORRECT: Use BigInt for 64-bit permission values
const perms = BigInt(permissions);
const hasAdmin = (perms & BigInt(0x8)) !== BigInt(0);

// WRONG: Regular numbers may lose precision
const perms = parseInt(permissions);  // Can overflow!
```

---

## 4. Implementation Guide

### Step 1: Update Type Definitions

```typescript
// apps/web/src/types/discord.ts (new file)

export interface DiscordGuild {
  id: string;
  name: string;
  icon: string | null;
  owner: boolean;
  permissions: string;  // Bitfield as string
  features: string[];
}

export interface ManagedGuild extends DiscordGuild {
  canManage: true;
}

// Permission constants
export const DiscordPermissions = {
  ADMINISTRATOR: BigInt(0x8),
  MANAGE_GUILD: BigInt(0x20),
  MANAGE_CHANNELS: BigInt(0x10),
  MANAGE_ROLES: BigInt(0x10000000),
  VIEW_AUDIT_LOG: BigInt(0x80),
} as const;
```

### Step 2: Create Permission Utility Functions

```typescript
// apps/web/src/lib/permissions.ts (new file)

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
```

### Step 3: Update Dashboard Page

```typescript
// apps/web/src/app/dashboard/page.tsx

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
      // Cache for 60 seconds to reduce API calls
      next: { revalidate: 60 },
    });

    if (!response.ok) {
      console.error(`Discord API error: ${response.status}`);
      return [];
    }

    const guilds: DiscordGuild[] = await response.json();
    
    // CRITICAL: Filter to only manageable guilds
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

  // This now only returns guilds the user can manage
  const guilds = await getUserGuilds(session.accessToken);

  return (
    <main className="min-h-screen bg-discord-darkest">
      <header className="bg-discord-darker border-b border-gray-800">
        <div className="max-w-7xl mx-auto px-4 py-4">
          <h1 className="text-xl font-bold text-white">
            Discord Community Intelligence
          </h1>
          <p className="text-sm text-gray-400 mt-1">
            Showing servers you can manage
          </p>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 py-8">
        <h2 className="text-2xl font-bold text-white mb-6">
          Your Manageable Servers ({guilds.length})
        </h2>

        {guilds.length === 0 ? (
          <div className="bg-discord-darker rounded-lg p-8 text-center">
            <p className="text-gray-400">
              No servers found where you have management permissions.
            </p>
            <p className="text-sm text-gray-500 mt-2">
              You need Administrator or Manage Server permission.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {guilds.map((guild) => (
              <Link
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
                    {guild.name.charAt(0)}
                  </div>
                )}
                <div>
                  <h3 className="text-white font-semibold">{guild.name}</h3>
                  <p className="text-sm text-gray-400">
                    {guild.owner ? "Owner" : "Manager"}
                  </p>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
```

### Step 4: Add Server-Side Validation for Guild Pages

```typescript
// apps/web/src/app/dashboard/[guildId]/page.tsx

import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { canManageGuildById } from "@/lib/permissions";
import type { DiscordGuild } from "@/types/discord";

async function getUserGuilds(accessToken: string): Promise<DiscordGuild[]> {
  const response = await fetch("https://discord.com/api/users/@me/guilds", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) return [];
  return response.json();
}

interface GuildPageProps {
  params: Promise<{ guildId: string }>;
}

export default async function GuildPage({ params }: GuildPageProps) {
  const session = await auth();

  if (!session) {
    redirect("/login");
  }

  const { guildId } = await params;

  // CRITICAL: Server-side permission validation
  const guilds = await getUserGuilds(session.accessToken);
  const hasAccess = canManageGuildById(guilds, guildId);

  if (!hasAccess) {
    // User doesn't have permission - redirect with error
    redirect("/dashboard?error=unauthorized");
  }

  // ... rest of the component (fetch channels, render UI, etc.)
}
```

### Step 5: Create Middleware for Additional Protection (Optional)

```typescript
// apps/web/src/middleware.ts

import { auth } from "@/lib/auth";
import { NextResponse } from "next/server";

export default auth((req) => {
  const isLoggedIn = !!req.auth;
  const isOnDashboard = req.nextUrl.pathname.startsWith("/dashboard");

  if (isOnDashboard && !isLoggedIn) {
    return NextResponse.redirect(new URL("/login", req.url));
  }

  return NextResponse.next();
});

export const config = {
  matcher: ["/dashboard/:path*"],
};
```

---

## 5. Testing Strategy

### Unit Tests

```typescript
// apps/web/src/__tests__/permissions.test.ts

import { describe, it, expect } from "vitest";
import {
  hasPermission,
  canManageGuild,
  filterManageableGuilds,
} from "@/lib/permissions";
import { DiscordPermissions } from "@/types/discord";

describe("hasPermission", () => {
  it("should detect ADMINISTRATOR permission", () => {
    // 0x8 = 8 in decimal
    expect(hasPermission("8", DiscordPermissions.ADMINISTRATOR)).toBe(true);
    expect(hasPermission("0", DiscordPermissions.ADMINISTRATOR)).toBe(false);
  });

  it("should detect MANAGE_GUILD permission", () => {
    // 0x20 = 32 in decimal
    expect(hasPermission("32", DiscordPermissions.MANAGE_GUILD)).toBe(true);
    expect(hasPermission("16", DiscordPermissions.MANAGE_GUILD)).toBe(false);
  });

  it("should handle combined permissions", () => {
    // 0x28 = ADMINISTRATOR (0x8) + MANAGE_GUILD (0x20) = 40
    expect(hasPermission("40", DiscordPermissions.ADMINISTRATOR)).toBe(true);
    expect(hasPermission("40", DiscordPermissions.MANAGE_GUILD)).toBe(true);
  });

  it("should handle large permission values with BigInt", () => {
    // Real Discord permission value: 2147483647
    const realPermissions = "2147483647";
    expect(hasPermission(realPermissions, DiscordPermissions.ADMINISTRATOR)).toBe(true);
  });
});

describe("canManageGuild", () => {
  it("should return true for admin", () => {
    expect(canManageGuild("8")).toBe(true);
  });

  it("should return true for manage_guild", () => {
    expect(canManageGuild("32")).toBe(true);
  });

  it("should return false for regular member", () => {
    // Only VIEW_CHANNEL (0x400) = 1024
    expect(canManageGuild("1024")).toBe(false);
  });
});

describe("filterManageableGuilds", () => {
  it("should filter out non-manageable guilds", () => {
    const guilds = [
      { id: "1", name: "Admin Server", owner: false, permissions: "8", icon: null, features: [] },
      { id: "2", name: "Manager Server", owner: false, permissions: "32", icon: null, features: [] },
      { id: "3", name: "Member Server", owner: false, permissions: "1024", icon: null, features: [] },
      { id: "4", name: "Owner Server", owner: true, permissions: "0", icon: null, features: [] },
    ];

    const result = filterManageableGuilds(guilds);

    expect(result).toHaveLength(3);
    expect(result.map((g) => g.id)).toEqual(["1", "2", "4"]);
  });
});
```

### Integration Test

```typescript
// apps/web/src/__tests__/dashboard.integration.test.ts

import { describe, it, expect, vi } from "vitest";

describe("Dashboard RBAC", () => {
  it("should only show manageable guilds", async () => {
    // Mock Discord API response
    const mockGuilds = [
      { id: "1", name: "Can Manage", permissions: "32", owner: false },
      { id: "2", name: "Cannot Manage", permissions: "1024", owner: false },
    ];

    // ... test that only "Can Manage" appears in rendered output
  });

  it("should redirect unauthorized access to guild page", async () => {
    // Test accessing /dashboard/123 without permission
    // Should redirect to /dashboard?error=unauthorized
  });
});
```

---

## 6. Security Considerations

### Defense in Depth

1. **Client-side filtering**: Filter guild list before rendering (UX)
2. **Server-side validation**: Check permissions on every guild-specific page load
3. **API-level validation**: Backend API should also verify guild access

### Rate Limiting

Discord's API has rate limits. Cache guild list to avoid excessive calls:

```typescript
// Cache guild list for 60 seconds
const response = await fetch("https://discord.com/api/users/@me/guilds", {
  headers: { Authorization: `Bearer ${accessToken}` },
  next: { revalidate: 60 },
});
```

### Token Security

- Never expose access tokens in client-side code
- Use server components for Discord API calls
- Refresh tokens before expiration

---

## 7. References

- [Discord API Permissions Documentation](https://discord.com/developers/docs/topics/permissions)
- [NextAuth.js Discord Provider](https://next-auth.js.org/providers/discord)
- [Auth.js RBAC Guide](https://authjs.dev/guides/role-based-access-control)
- [Discord.js PermissionsBitField](https://discord.js.org/docs/packages/discord.js/main/PermissionsBitField:Class)

---

## 8. Checklist

- [ ] Create `apps/web/src/types/discord.ts`
- [ ] Create `apps/web/src/lib/permissions.ts`
- [ ] Update `apps/web/src/app/dashboard/page.tsx`
- [ ] Update `apps/web/src/app/dashboard/[guildId]/page.tsx`
- [ ] Add unit tests for permission utilities
- [ ] Add integration tests for RBAC flow
- [ ] Test with real Discord accounts (admin vs member)
