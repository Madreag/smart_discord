#!/usr/bin/env python3
"""
Sync Verification Script - Checks and repairs Postgres-Qdrant synchronization.

Usage:
    python scripts/verify_sync.py --guild-id 123456789
    python scripts/verify_sync.py --guild-id 123456789 --repair
    python scripts/verify_sync.py --guild-id 123456789 --force-reindex
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from apps.api.src.services.storage_service import storage_service
from apps.api.src.services.qdrant_service import qdrant_service


def print_sync_health(guild_id: int) -> None:
    """Print sync health summary."""
    health = storage_service.get_sync_health(guild_id)
    
    print("\n" + "=" * 60)
    print(f"SYNC HEALTH REPORT - Guild {guild_id}")
    print("=" * 60)
    
    print(f"\nTotal Messages (indexed channels): {health.total_messages:,}")
    print(f"Synced to Qdrant:                   {health.synced:,}")
    print(f"Pending sync:                       {health.pending:,}")
    print(f"Stale (needs re-index):             {health.stale:,}")
    print(f"\nSync Percentage: {health.sync_percentage:.1f}%")
    
    # Health status with color
    if health.health == "healthy":
        status = "✓ HEALTHY"
    elif health.health == "degraded":
        status = "⚠ DEGRADED"
    else:
        status = "✗ CRITICAL"
    
    print(f"Health Status:   {status}")
    print("=" * 60)


def verify_qdrant_points(guild_id: int) -> dict:
    """Verify Qdrant points exist in Postgres."""
    print("\nVerifying Qdrant points...")
    
    # Get all points from Qdrant for this guild
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        client = QdrantClient(host="localhost", port=6333)
        
        # Scroll through all points for this guild
        points = []
        offset = None
        
        while True:
            result = client.scroll(
                collection_name="discord_sessions",
                scroll_filter=Filter(
                    must=[FieldCondition(key="guild_id", match=MatchValue(value=guild_id))]
                ),
                limit=100,
                offset=offset,
                with_payload=False,
            )
            
            batch, offset = result
            if not batch:
                break
            
            points.extend([str(p.id) for p in batch])
            
            if offset is None:
                break
        
        print(f"  Found {len(points)} points in Qdrant")
        
        if points:
            verification = storage_service.verify_qdrant_points(guild_id, points)
            print(f"  Valid (in Postgres):   {len(verification['valid'])}")
            print(f"  Orphaned (no Postgres): {len(verification['orphaned'])}")
            return verification
        
        return {"valid": [], "orphaned": []}
        
    except Exception as e:
        print(f"  Error: {e}")
        return {"valid": [], "orphaned": []}


def show_unsynced_sample(guild_id: int, limit: int = 5) -> None:
    """Show sample of unsynced messages."""
    unsynced = storage_service.get_unsynced_messages(guild_id, limit=limit)
    
    if unsynced:
        print(f"\nSample unsynced message IDs: {unsynced}")
    
    stale = storage_service.get_stale_messages(guild_id, limit=limit)
    
    if stale:
        print(f"Sample stale message IDs: {stale}")


def repair_sync(guild_id: int, force: bool = False) -> None:
    """Repair sync issues."""
    print("\n" + "=" * 60)
    print(f"REPAIRING SYNC - Guild {guild_id}")
    print("=" * 60)
    
    if force:
        print("\n⚠ FORCE mode: Will reset ALL messages for re-indexing")
    
    count = storage_service.reset_sync_status(guild_id, force=force)
    
    print(f"\nReset {count} messages for re-indexing")
    print("\nTo complete the repair, run:")
    print(f"  python scripts/index_to_qdrant.py --guild-id {guild_id}")


def main():
    parser = argparse.ArgumentParser(description="Verify Postgres-Qdrant sync")
    parser.add_argument("--guild-id", type=int, required=True, help="Guild ID to check")
    parser.add_argument("--repair", action="store_true", help="Repair pending/stale items")
    parser.add_argument("--force-reindex", action="store_true", help="Force re-index everything")
    parser.add_argument("--verify-qdrant", action="store_true", help="Verify Qdrant points")
    
    args = parser.parse_args()
    
    # Show current health
    print_sync_health(args.guild_id)
    
    # Show sample of issues
    show_unsynced_sample(args.guild_id)
    
    # Verify Qdrant points if requested
    if args.verify_qdrant:
        verify_qdrant_points(args.guild_id)
    
    # Repair if requested
    if args.repair or args.force_reindex:
        repair_sync(args.guild_id, force=args.force_reindex)
        
        # Show updated health
        print("\nAfter repair:")
        print_sync_health(args.guild_id)


if __name__ == "__main__":
    main()
