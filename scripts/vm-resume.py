#!/usr/bin/env python3
"""
blockhost-vm-resume — Resume a suspended VM.

Reactivates a suspended VM: starts the domain via root agent, re-applies
bridge port isolation (libvirt creates a fresh tap on start), and updates
the database. Optionally extends the expiry date.

Called by the engine reconciler when a SubscriptionExtended event comes in
for an expired (but not yet destroyed) subscription.

Contract:
  blockhost-vm-resume <name> [--extend-days N] [--mock] [--dry-run]
  exit 0 on success, 1 on failure.
"""

import argparse
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from blockhost.config import load_db_config
from blockhost.root_agent import RootAgentError, call
from blockhost.vm_db import get_database


VM_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$')


def err(msg):
    """Print to stderr with a consistent prefix."""
    print(f"[vm-resume] {msg}", file=sys.stderr)


def _get_vm_tap_interface(domain):
    """Discover the tap device for a domain's bridge interface.

    Read-only — blockhost user has virsh access without root agent.
    """
    try:
        r = subprocess.run(
            ["virsh", "domiflist", domain],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return None
        for line in r.stdout.strip().splitlines()[2:]:  # skip header + separator
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "bridge":
                return parts[0]
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Resume a suspended BlockHost VM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    blockhost-vm-resume myvm                     # Resume with default extension
    blockhost-vm-resume myvm --extend-days 30    # Resume and extend by 30 days
    blockhost-vm-resume myvm --dry-run           # Show what would happen
        """,
    )
    parser.add_argument("name", help="VM name (libvirt domain name)")
    parser.add_argument("--extend-days", type=int, default=None,
                        help="Extend expiry by N days (default: from db.yaml or 30)")
    parser.add_argument("--mock", action="store_true",
                        help="Use mock database")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without making changes")

    args = parser.parse_args()

    if not VM_NAME_RE.match(args.name):
        err(f"Invalid VM name: {args.name!r}")
        return 1

    db = get_database(use_mock=args.mock)
    vm = db.get_vm(args.name)

    if not vm:
        err(f"VM '{args.name}' not found")
        return 1

    status = vm.get("status", "unknown")
    if status != "suspended":
        err(f"VM '{args.name}' is not suspended (status: {status})")
        if status == "active":
            err("  The VM is already active.")
        elif status == "destroyed":
            err("  The VM has been destroyed and cannot be resumed.")
        return 1

    print(f"Resuming VM: {args.name}")
    print(f"  Current status: {status}")
    print(f"  Owner: {vm.get('owner', 'unknown')}")
    print(f"  Suspended at: {vm.get('suspended_at', 'N/A')}")

    try:
        db_config = load_db_config()
    except FileNotFoundError:
        db_config = {}

    extend_days = args.extend_days if args.extend_days is not None else db_config.get("default_expiry_days", 30)
    if extend_days < 1:
        err("--extend-days must be at least 1")
        return 1
    new_expiry = datetime.now(timezone.utc) + timedelta(days=extend_days)
    print(f"  New expiry: {new_expiry.isoformat()} (+{extend_days} days)")

    if args.dry_run:
        print("\n[DRY RUN] Would:")
        print(f"  - Start domain {args.name}")
        print("  - Re-apply bridge port isolation")
        print("  - Set status to 'active'")
        print(f"  - Set expiry to {new_expiry.isoformat()}")
        return 0

    print("\nStarting domain...")
    try:
        result = call("virsh-start", domain=args.name)
        if result.get("ok"):
            print("  Domain started")
        else:
            err_text = result.get("error", "unknown")
            # Idempotent: if libvirt reports already-running, treat as success
            if "already" in err_text.lower():
                print("  Domain already running (continuing)")
            else:
                err(f"virsh-start failed: {err_text}")
                return 1
    except RootAgentError as e:
        err(f"Root agent error: {e}")
        return 1

    # Re-apply bridge port isolation (libvirt creates a new tap on start;
    # isolation from the original vm-create is gone). Non-fatal — VM works
    # without it, but inter-VM L2 traffic would be possible.
    tap = _get_vm_tap_interface(args.name)
    if tap:
        try:
            r = call("bridge-port-isolate", dev=tap)
            if r.get("ok"):
                print(f"  Bridge port isolation enabled on {tap}")
            else:
                print(f"  WARNING: bridge port isolation failed on {tap}: {r.get('error')}")
        except RootAgentError as e:
            print(f"  WARNING: bridge port isolation failed: {e}")
    else:
        print("  WARNING: Could not determine tap interface for bridge port isolation")

    try:
        db.mark_active(args.name, new_expiry=new_expiry)
        print("  Database: status='active', expiry extended")
    except Exception as e:
        err(f"Database update failed: {e}")
        err("WARNING: VM started but database may be inconsistent")
        return 1

    print(f"\nVM '{args.name}' resumed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
