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


DEFAULT_USERNAME = "admin"
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

    gecos = f"wallet={args.wallet_address},nft={args.nft_id}"
    err(f"Updating GECOS for {args.name}: {gecos}")

    # shlex.quote protects the sh -c context inside the VM — gecos values
    # contain `,` and `=`, and the wallet address comes from the engine.
    command = f"usermod -c {shlex.quote(gecos)} {shlex.quote(DEFAULT_USERNAME)}"

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
