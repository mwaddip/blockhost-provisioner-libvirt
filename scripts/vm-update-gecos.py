#!/usr/bin/env python3
"""
blockhost-vm-update-gecos — Update a VM user's GECOS field via QEMU guest agent.

Contract:
  blockhost-vm-update-gecos <name> <wallet-address> --nft-id <token_id>
  exit 0 on success, 1 on failure.

Called by the engine reconciler when an NFT ownership transfer is detected.
The GECOS field (wallet=<addr>,nft=<id>) is read by the PAM module to verify
the VM user's wallet address.

Execution path: delegates to `blockhost-vm-guest-exec` so all in-VM command
execution flows through a single primitive. The GECOS string is built here;
`usermod -c` inside the VM applies it atomically.

The VM must be running with a responsive QEMU guest agent. If the VM is
stopped or suspended, the command fails and the reconciler retries next cycle.
"""

import argparse
import shlex
import subprocess
import sys

from blockhost.vm_db import get_database


FALLBACK_USERNAME = "admin"
GUEST_EXEC_CLI = "blockhost-vm-guest-exec"


def err(msg):
    """Print to stderr."""
    print(f"[vm-update-gecos] {msg}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Update VM user GECOS field via QEMU guest agent",
    )
    parser.add_argument("name", help="VM name (libvirt domain name)")
    parser.add_argument("wallet_address", help="New owner wallet address")
    parser.add_argument("--nft-id", required=True, help="NFT token ID")

    args = parser.parse_args()

    # Resolve the in-VM username from the DB record. Pre-username VMs (or
    # records missing for any reason) fall back to "admin" — the only user
    # any VM created before this change was provisioned with.
    db = get_database()
    vm = db.get_vm(args.name)
    username = (vm.get("username") if vm else None) or FALLBACK_USERNAME
    if not vm or not vm.get("username"):
        err(f"WARNING: no username in DB for {args.name}, using fallback {FALLBACK_USERNAME!r}")

    gecos = f"wallet={args.wallet_address},nft={args.nft_id}"
    err(f"Updating GECOS for {args.name} (user {username}): {gecos}")

    # shlex.quote protects the sh -c context inside the VM — gecos values
    # contain `,` and `=`, and the wallet address comes from the engine.
    command = f"usermod -c {shlex.quote(gecos)} {shlex.quote(username)}"

    try:
        result = subprocess.run(
            [GUEST_EXEC_CLI, args.name, command],
            check=False,
        )
    except FileNotFoundError:
        err(f"{GUEST_EXEC_CLI} not found on PATH (blockhost-provisioner-libvirt not installed?)")
        sys.exit(1)

    if result.returncode != 0:
        err(f"Failed (exit {result.returncode})")
        sys.exit(result.returncode)

    err(f"GECOS updated for {args.name}")
    sys.exit(0)


if __name__ == "__main__":
    main()
