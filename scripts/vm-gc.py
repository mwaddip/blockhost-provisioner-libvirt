#!/usr/bin/env python3
"""
blockhost-vm-gc — Garbage collect expired VMs (two-phase: suspend then destroy).

Contract:
  blockhost-vm-gc [--execute] [--suspend-only] [--destroy-only] [--grace-days N] [--mock]
  Dry-run by default. --execute to actually perform actions.
  exit 0 on success, 1 on failure.

Implementation notes:
  - Phase 1 (suspend): VMs past expiry → virsh shutdown (graceful)
  - Phase 2 (destroy): VMs past expiry + grace period → full cleanup
  - Uses the same VMDatabase as the Proxmox provisioner (from blockhost-common)
  - Grace days from db.yaml or --grace-days override
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Garbage collect expired BlockHost VMs")
    parser.add_argument("--execute", action="store_true", help="Actually perform actions (dry-run without)")
    parser.add_argument("--suspend-only", action="store_true", help="Only run suspend phase")
    parser.add_argument("--destroy-only", action="store_true", help="Only run destroy phase")
    parser.add_argument("--grace-days", type=int, help="Override grace period in days")
    parser.add_argument("--mock", action="store_true", help="Use mock database")

    args = parser.parse_args()

    # TODO: Implement garbage collection
    # 1. Load VM database
    # 2. Find expired VMs (check NFT expiry on-chain or in DB)
    # 3. Phase 1: shut down running expired VMs
    # 4. Phase 2: destroy VMs past grace period
    # 5. Report counts

    print("Suspend: 0 candidates")
    print("Destroy: 0 candidates")
    if not args.execute:
        print("(dry-run — use --execute to apply)")


if __name__ == "__main__":
    main()
