#!/usr/bin/env python3
"""
blockhost-vm-resume — Resume a suspended VM.

Contract:
  blockhost-vm-resume <name> [--extend-days N] [--mock] [--dry-run]
  exit 0 on success, 1 on failure.
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Resume a suspended BlockHost VM")
    parser.add_argument("name", help="VM name")
    parser.add_argument("--extend-days", type=int, help="Extend subscription by N days")
    parser.add_argument("--mock", action="store_true", help="Use mock database")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")

    args = parser.parse_args()

    # TODO: Implement VM resume
    # 1. Verify VM exists and is suspended
    # 2. Start the domain (virsh start)
    # 3. If --extend-days: update expiry in database
    # 4. Report success

    print(f"ERROR: not yet implemented", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
