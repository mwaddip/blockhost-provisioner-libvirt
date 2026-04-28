#!/usr/bin/env python3
"""
blockhost-vm-gc — Two-phase garbage collection of expired VMs.

Phase 1 (suspend): Active VMs past their expiry are gracefully shut down
                   and marked suspended. Disks remain intact.
Phase 2 (destroy): Suspended VMs past expiry + grace period are destroyed
                   via blockhost-vm-destroy (which handles VM teardown,
                   storage cleanup, IPv6 route removal, and DB update).

Dry-run by default. Pass --execute to actually act.

Designed to run as a systemd timer (daily, as the blockhost user). Talks
to libvirt through the root agent; shells out to blockhost-vm-destroy
for full Phase 2 cleanup so the cleanup logic stays in one place.

SPECIAL profile: S8 P6 E9 C4 I6 A5 L8 — destroys things, must be careful.
"""

import argparse
import subprocess
import sys
from datetime import datetime, timezone

from blockhost.config import load_db_config
from blockhost.root_agent import RootAgentError, call
from blockhost.vm_db import get_database


def _shutdown_vm(name):
    """Graceful shutdown via root agent. Force-stops on graceful failure.

    Returns (ok, message). 'Already stopped' counts as ok — the goal is
    state, not action.
    """
    try:
        result = call("virsh-shutdown", domain=name)
        if result.get("ok"):
            return True, "Shutdown signal sent"
        if "not running" in result.get("error", "").lower():
            return True, "VM already stopped"
        # Fall through to force-stop
        result = call("virsh-destroy", domain=name)
        if result.get("ok"):
            return True, "Force-stopped (graceful shutdown failed)"
        if "not running" in result.get("error", "").lower():
            return True, "VM already stopped"
        return False, result.get("error", "unknown")
    except RootAgentError as e:
        return False, str(e)


def _format_timedelta(expiry_str):
    """Render how long ago a VM expired, in days/hours."""
    expiry = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
    delta = datetime.now(timezone.utc) - expiry
    days = delta.days
    if days < 0:
        return f"expires in {-days} days"
    if days == 0:
        return f"expired {delta.seconds // 3600} hours ago"
    if days == 1:
        return "expired 1 day ago"
    return f"expired {days} days ago"


def phase_suspend(db, execute, verbose):
    """Phase 1: shutdown VMs past expiry, mark suspended.

    Returns (success_count, error_count).
    """
    print("\n" + "=" * 60)
    print("PHASE 1: SUSPEND EXPIRED VMs")
    print("=" * 60)

    vms = db.get_vms_to_suspend()
    if not vms:
        print("No VMs to suspend.")
        return 0, 0

    print(f"Found {len(vms)} VM(s) to suspend:\n")
    success = errors = 0

    for vm in vms:
        name = vm["vm_name"]
        owner = vm.get("owner", "unknown")
        info = _format_timedelta(vm["expires_at"])

        print(f"  VM: {name}")
        print(f"    Owner: {owner}")
        print(f"    Status: {info}")
        if verbose:
            print(f"    IP: {vm.get('ip_address', 'N/A')}")

        if execute:
            print("    Shutting down...")
            ok, msg = _shutdown_vm(name)
            if ok:
                print(f"    {msg}")
                try:
                    db.mark_suspended(name)
                    print("    Marked as suspended")
                    success += 1
                except Exception as e:
                    print(f"    Error updating database: {e}")
                    errors += 1
            else:
                print(f"    Failed: {msg}")
                errors += 1
        else:
            print("    [DRY RUN] Would suspend")
            success += 1
        print()

    return success, errors


def phase_destroy(db, grace_days, execute, verbose):
    """Phase 2: destroy past-grace VMs by shelling to blockhost-vm-destroy.

    blockhost-vm-destroy is idempotent and handles the full teardown
    (virsh stop/undefine, qcow2 overlay, cloud-init artifacts, IPv6 route,
    DB mark_destroyed). Centralising here avoids re-implementing cleanup.

    Returns (success_count, error_count).
    """
    print("\n" + "=" * 60)
    print("PHASE 2: DESTROY PAST-GRACE VMs")
    print("=" * 60)

    vms = db.get_vms_to_destroy(grace_days=grace_days)
    if not vms:
        print("No VMs to destroy.")
        return 0, 0

    print(f"Found {len(vms)} VM(s) to destroy:\n")
    success = errors = 0

    for vm in vms:
        name = vm["vm_name"]
        owner = vm.get("owner", "unknown")
        status = vm.get("status", "unknown")
        info = _format_timedelta(vm["expires_at"])

        print(f"  VM: {name}")
        print(f"    Owner: {owner}")
        print(f"    Status: {status}, {info}")
        if verbose:
            print(f"    IP: {vm.get('ip_address', 'N/A')}")
            print(f"    Suspended at: {vm.get('suspended_at', 'N/A')}")

        if execute:
            print("    Destroying via blockhost-vm-destroy...")
            try:
                result = subprocess.run(
                    ["blockhost-vm-destroy", name],
                    capture_output=True, text=True, timeout=300,
                )
                if result.returncode == 0:
                    print("    Destroyed")
                    success += 1
                else:
                    err_text = (result.stderr.strip() or result.stdout.strip())[-300:]
                    print(f"    Failed: {err_text}")
                    errors += 1
            except subprocess.TimeoutExpired:
                print("    Failed: blockhost-vm-destroy timed out")
                errors += 1
            except FileNotFoundError:
                print("    Failed: blockhost-vm-destroy not in PATH")
                errors += 1
        else:
            print("    [DRY RUN] Would destroy")
            success += 1
        print()

    return success, errors


def main():
    parser = argparse.ArgumentParser(
        description="Two-phase VM garbage collection: suspend then destroy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    blockhost-vm-gc                           # Dry run both phases
    blockhost-vm-gc --execute                 # Execute both phases
    blockhost-vm-gc --execute --suspend-only  # Phase 1 only
    blockhost-vm-gc --execute --destroy-only  # Phase 2 only
    blockhost-vm-gc --mock --execute          # Test against mock DB
        """,
    )
    parser.add_argument("--execute", action="store_true",
                        help="Actually perform actions (default: dry-run)")
    parser.add_argument("--suspend-only", action="store_true",
                        help="Only run Phase 1 (suspend expired VMs)")
    parser.add_argument("--destroy-only", action="store_true",
                        help="Only run Phase 2 (destroy past-grace VMs)")
    parser.add_argument("--grace-days", type=int, default=None,
                        help="Override grace period from db.yaml")
    parser.add_argument("--mock", action="store_true",
                        help="Use mock database for testing")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")

    args = parser.parse_args()

    if args.suspend_only and args.destroy_only:
        print("Error: --suspend-only and --destroy-only are mutually exclusive",
              file=sys.stderr)
        return 1

    try:
        db_config = load_db_config()
    except FileNotFoundError:
        db_config = {}

    grace_days = args.grace_days if args.grace_days is not None else db_config.get("gc_grace_days", 7)
    if grace_days < 0:
        print("Error: grace days must be non-negative", file=sys.stderr)
        return 1

    print("=" * 60)
    print(f"VM Garbage Collection - {datetime.now().isoformat()}")
    print("=" * 60)
    print(f"Mode: {'EXECUTE' if args.execute else 'DRY RUN'}")
    print(f"Grace period: {grace_days} days")
    if args.suspend_only:
        print("Running: Phase 1 only (suspend)")
    elif args.destroy_only:
        print("Running: Phase 2 only (destroy)")
    else:
        print("Running: Both phases")

    db = get_database(use_mock=args.mock)

    total_success = total_errors = 0

    if not args.destroy_only:
        s, e = phase_suspend(db, args.execute, args.verbose)
        total_success += s
        total_errors += e

    if not args.suspend_only:
        s, e = phase_destroy(db, grace_days, args.execute, args.verbose)
        total_success += s
        total_errors += e

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    print(f"  {'Processed' if args.execute else 'Would process'}: {total_success}")
    print(f"  Errors: {total_errors}")

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
