#!/usr/bin/env python3
"""
blockhost-mint-nft — Mint an access credential NFT.

Contract:
  blockhost-mint-nft --owner-wallet <0x> --machine-id <name>
      [--user-encrypted <hex> --public-secret <str>]
      [--dry-run]
  stdout: transaction hash on success
  exit 0 on success, 1 on failure.

Implementation notes:
  This is essentially identical to the Proxmox provisioner's mint_nft.py —
  NFT minting is hypervisor-agnostic. The only difference is that this
  version ships with the libvirt package.

  Consider: should mint_nft.py move to blockhost-common instead of being
  duplicated per provisioner? It's not hypervisor-specific.
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Mint a BlockHost access credential NFT")
    parser.add_argument("--owner-wallet", required=True, help="Owner wallet address (0x...)")
    parser.add_argument("--machine-id", required=True, help="VM/machine name")
    parser.add_argument("--user-encrypted", help="Encrypted connection details (hex)")
    parser.add_argument("--public-secret", help="Public secret for verification")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")

    args = parser.parse_args()

    # TODO: Implement NFT minting
    # This can be largely copied from the Proxmox provisioner's mint_nft.py
    # or better yet, extracted to blockhost-common as a shared utility.

    print("ERROR: not yet implemented", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
