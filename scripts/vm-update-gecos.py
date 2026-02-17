#!/usr/bin/env python3
"""
blockhost-vm-update-gecos — Update a VM user's GECOS field via QEMU guest agent.

Contract:
  blockhost-vm-update-gecos <name> <wallet-address> --nft-id <token_id>
  exit 0 on success, 1 on failure.

Called by the engine reconciler when an NFT ownership transfer is detected.
The GECOS field (wallet=<addr>,nft=<id>) is read by the PAM module to verify
the VM user's wallet address.

The VM must be running with a responsive QEMU guest agent. If the VM is
stopped or suspended, the command fails and the reconciler retries next cycle.
"""

import argparse
import sys


DEFAULT_USERNAME = "admin"


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

    try:
        from blockhost.root_agent import call, RootAgentError
    except ImportError:
        err("blockhost-common not installed (cannot import blockhost.root_agent)")
        sys.exit(1)

    try:
        result = call(
            'virsh-update-gecos',
            domain=args.name,
            username=DEFAULT_USERNAME,
            gecos=gecos,
        )
    except RootAgentError as exc:
        err(f"Root agent error: {exc}")
        sys.exit(1)

    if not result.get('ok'):
        err(f"Failed: {result.get('error', 'unknown error')}")
        sys.exit(1)

    err(f"GECOS updated for {args.name}")
    sys.exit(0)


if __name__ == "__main__":
    main()
