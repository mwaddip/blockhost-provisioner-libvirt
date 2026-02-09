#!/usr/bin/env python3
"""
blockhost-vm-create — Create a VM on libvirt/KVM with cloud-init.

Contract:
  blockhost-vm-create <name> --owner-wallet <0x>
      [--cpu N] [--memory N] [--disk N]
      [--apply]
      [--cloud-init-content <path>]
      [--skip-mint]
      [--user-signature <hex> --public-secret <str>]

  stdout (JSON on success):
    {"status":"ok","vm_name":"...","ip":"...","ipv6":"...","vmid":"...","nft_token_id":N,"username":"..."}

  exit 0 on success, 1 on failure.

Implementation notes:
  - Uses virt-install + cloud-init ISO to provision a VM from the base template image
  - VM "vmid" is the libvirt domain name (same as vm_name for libvirt)
  - IP allocation from the configured pool in db.yaml
  - cloud-init ISO built per-VM in /var/lib/blockhost/cloud-init/
  - Base image cloned from template via qemu-img create -b (backing file)
"""

import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description="Create a BlockHost VM on libvirt/KVM")
    parser.add_argument("name", help="VM name")
    parser.add_argument("--owner-wallet", required=True, help="Owner wallet address (0x...)")
    parser.add_argument("--cpu", type=int, default=1, help="Number of vCPUs")
    parser.add_argument("--memory", type=int, default=2048, help="Memory in MB")
    parser.add_argument("--disk", type=int, default=20, help="Disk size in GB")
    parser.add_argument("--apply", action="store_true", help="Actually create the VM (dry-run without)")
    parser.add_argument("--cloud-init-content", help="Path to pre-rendered cloud-init YAML")
    parser.add_argument("--skip-mint", action="store_true", help="Skip NFT minting")
    parser.add_argument("--no-mint", action="store_true", help="Skip NFT minting (engine handles it)")
    parser.add_argument("--user-signature", help="User signature for encrypted credentials")
    parser.add_argument("--public-secret", help="Public secret for signature verification")
    parser.add_argument("--mock", action="store_true", help="Use mock database")

    args = parser.parse_args()

    # TODO: Implement VM creation
    # 1. Load config from db.yaml (storage_pool, network, ip_pool)
    # 2. Allocate IP from pool
    # 3. Reserve NFT token ID in database
    # 4. Clone base image via qemu-img create -b <template> <vm-disk>
    # 5. Generate cloud-init ISO (or use --cloud-init-content)
    # 6. Define domain via virt-install --import
    # 7. If --apply: start the domain
    # 8. If not --skip-mint and not --no-mint: mint NFT
    # 9. Output JSON summary

    print(json.dumps({
        "status": "error",
        "error": "not yet implemented"
    }))
    sys.exit(1)


if __name__ == "__main__":
    main()
