#!/usr/bin/env python3
"""
blockhost-vm-create — Create a VM on libvirt/KVM with cloud-init.

Contract:
  blockhost-vm-create <name> --owner-wallet <0x>
      [--cpu N] [--memory N] [--disk N]
      [--apply]
      [--cloud-init-content <path>]
      [--skip-mint] [--no-mint]
      [--user-signature <hex> --public-secret <str>]
      [--mock]

  stdout (JSON on success):
    {"status":"ok","vm_name":"...","ip":"...","ipv6":"...","vmid":"...","nft_token_id":N,"username":"..."}

  exit 0 on success, 1 on failure.

Implementation notes:
  - Domain XML generated directly (no Terraform, no virt-install dependency at runtime)
  - qcow2 overlay with backing file for CoW disk efficiency
  - cloud-init ISO via cloud-localds (NoCloud datasource)
  - Domain defined + started via root agent (virsh-define, virsh-start)
  - vmid = domain name (string) for libvirt, not integer like Proxmox
  - IPv6 route added via root agent for external connectivity

SPECIAL profile: S9 P7 E9 — robustness and reliability paramount.
Half-created VMs are nightmares. Each resource allocation is tracked so
cleanup on failure can undo partial work.
"""

import argparse
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path


# --- Constants ---

TEMPLATE_IMAGE = Path("/var/lib/blockhost/templates/blockhost-base.qcow2")
VM_DISK_DIR = Path("/var/lib/blockhost/vms")
CLOUD_INIT_DIR = Path("/var/lib/blockhost/cloud-init")
USERNAME = "user"


def err(msg):
    """Print to stderr."""
    print(f"[vm-create] {msg}", file=sys.stderr)


def fail(msg, allocated=None):
    """Print error JSON and exit. Attempts cleanup of partially allocated resources."""
    if allocated:
        _cleanup_partial(allocated)
    print(json.dumps({"status": "error", "error": msg}))
    sys.exit(1)


def _cleanup_partial(allocated):
    """Best-effort cleanup of resources allocated before failure."""
    name = allocated.get("name")
    err(f"Cleaning up partial allocation for {name}...")

    # Undo domain if it was defined
    if allocated.get("domain_defined"):
        try:
            from blockhost.root_agent import call
            call("virsh-destroy", domain=name)
        except Exception:
            pass
        try:
            from blockhost.root_agent import call
            call("virsh-undefine", domain=name, remove_storage=True)
        except Exception:
            pass

    # Remove disk overlay
    disk = allocated.get("disk_path")
    if disk and Path(disk).exists():
        try:
            Path(disk).unlink()
        except OSError:
            pass

    # Remove cloud-init artifacts
    ci_dir = allocated.get("cloud_init_dir")
    if ci_dir and Path(ci_dir).exists():
        import shutil
        try:
            shutil.rmtree(ci_dir)
        except OSError:
            pass

    # Release IP back to pool
    if allocated.get("ip") and allocated.get("db"):
        try:
            allocated["db"].release_ip(allocated["ip"])
        except Exception:
            pass

    # Release IPv6
    if allocated.get("ipv6") and allocated.get("db"):
        try:
            allocated["db"].release_ipv6(allocated["ipv6"])
        except Exception:
            pass

    # Mark NFT reservation as failed
    if allocated.get("nft_token_id") and allocated.get("db"):
        try:
            allocated["db"].mark_nft_failed(allocated["nft_token_id"])
        except Exception:
            pass


def generate_domain_xml(name, cpu, memory_mb, disk_path, cloud_init_iso, bridge_name):
    """Generate libvirt domain XML for a BlockHost VM.

    Design choices for a production multi-tenant hosting environment:
    - q35 machine type: modern chipset, PCIe support, better device topology
    - host-model CPU: exposes host features while allowing live migration
    - virtio for disk/net: paravirtualized I/O, near-native performance
    - cache='none' io='native': direct I/O bypasses host page cache, avoids
      double-caching with qcow2 metadata. Safe for data integrity on crash.
    - discard='unmap': guest TRIM/discard propagates to host, keeps sparse
      overlays from growing unbounded. Essential for CoW disk efficiency.
    - bridge interface: VMs attach to the host's Linux bridge (created by
      first-boot) for direct L2 access to the physical network.
    - serial console: allows 'virsh console' for debugging without VNC
    """
    return textwrap.dedent(f"""\
    <domain type='kvm'>
      <name>{name}</name>
      <memory unit='MiB'>{memory_mb}</memory>
      <vcpu placement='static'>{cpu}</vcpu>
      <os>
        <type arch='x86_64' machine='q35'>hvm</type>
        <boot dev='hd'/>
      </os>
      <cpu mode='host-model' check='partial'/>
      <features>
        <acpi/>
        <apic/>
      </features>
      <clock offset='utc'>
        <timer name='rtc' tickpolicy='catchup'/>
        <timer name='pit' tickpolicy='delay'/>
        <timer name='hpet' present='no'/>
      </clock>
      <on_poweroff>destroy</on_poweroff>
      <on_reboot>restart</on_reboot>
      <on_crash>destroy</on_crash>
      <devices>
        <disk type='file' device='disk'>
          <driver name='qemu' type='qcow2' cache='none' io='native' discard='unmap'/>
          <source file='{disk_path}'/>
          <target dev='vda' bus='virtio'/>
        </disk>
        <disk type='file' device='cdrom'>
          <driver name='qemu' type='raw'/>
          <source file='{cloud_init_iso}'/>
          <target dev='sda' bus='sata'/>
          <readonly/>
        </disk>
        <interface type='bridge'>
          <source bridge='{bridge_name}'/>
          <model type='virtio'/>
        </interface>
        <serial type='pty'>
          <target port='0'/>
        </serial>
        <console type='pty'>
          <target type='serial' port='0'/>
        </console>
        <channel type='unix'>
          <target type='virtio' name='org.qemu.guest_agent.0'/>
        </channel>
        <rng model='virtio'>
          <backend model='random'>/dev/urandom</backend>
        </rng>
      </devices>
    </domain>
    """)



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
    parser.add_argument("--expiry-days", type=int, default=30, help="Days until VM expires (default: 30)")
    parser.add_argument("--mock", action="store_true", help="Use mock database")

    args = parser.parse_args()

    # Track allocated resources for cleanup on failure
    allocated = {"name": args.name}

    # --- Load config ---
    try:
        from blockhost.config import load_db_config, load_web3_config, load_broker_allocation
    except ImportError:
        fail("blockhost-common not installed (cannot import blockhost.config)")

    try:
        db_config = load_db_config()
    except FileNotFoundError:
        fail("Config not found: /etc/blockhost/db.yaml (run wizard first)")

    web3_config = {}
    try:
        web3_config = load_web3_config()
    except FileNotFoundError:
        err("WARNING: web3-defaults.yaml not found, NFT variables will be empty")

    broker = None
    try:
        broker = load_broker_allocation()
    except Exception:
        err("WARNING: broker allocation not available, IPv6 will be empty")

    # Bridge name from db.yaml (written by main repo's first-boot)
    bridge_name = db_config.get("bridge", "br0")

    # --- Validate prerequisites ---

    if not TEMPLATE_IMAGE.exists():
        fail(f"Template image not found: {TEMPLATE_IMAGE} (run blockhost-build-template first)")

    # Ensure directories are traversable by libvirt-qemu (o+rx)
    for d in (TEMPLATE_IMAGE.parent, VM_DISK_DIR, CLOUD_INIT_DIR):
        d.mkdir(parents=True, exist_ok=True)
        st = d.stat()
        d.chmod(st.st_mode | 0o005)  # add o+rx

    # Template backing file must be readable by libvirt-qemu
    os.chmod(TEMPLATE_IMAGE, 0o644)

    disk_path = VM_DISK_DIR / f"{args.name}.qcow2"
    if disk_path.exists():
        fail(f"Disk already exists: {disk_path} (VM name collision?)")

    # --- Database operations ---

    from blockhost.vm_db import get_database
    db = get_database(use_mock=args.mock)
    allocated["db"] = db

    # Check for existing VM with same name
    existing = db.get_vm(args.name)
    if existing and existing.get("status") != "destroyed":
        fail(f"VM already exists in database: {args.name} (status: {existing.get('status')})")

    # Allocate IPv4 from pool
    ip = db.allocate_ip()
    if not ip:
        fail("No IPv4 addresses available in pool")
    allocated["ip"] = ip
    err(f"Allocated IP: {ip}")

    # Allocate IPv6 from broker prefix
    ipv6 = ""
    if broker:
        ipv6 = db.allocate_ipv6() or ""
    if ipv6:
        allocated["ipv6"] = ipv6
        err(f"Allocated IPv6: {ipv6}")
    else:
        err("No IPv6 allocated (broker unavailable or pool exhausted)")

    # Reserve NFT token ID
    nft_token_id = db.reserve_nft_token_id(args.name)
    allocated["nft_token_id"] = nft_token_id
    err(f"Reserved NFT token ID: {nft_token_id}")

    # --- Dry-run exit point ---

    if not args.apply:
        err("Dry-run mode (pass --apply to create)")
        print(json.dumps({
            "status": "ok",
            "vm_name": args.name,
            "ip": ip,
            "ipv6": ipv6,
            "vmid": args.name,
            "nft_token_id": nft_token_id,
            "username": USERNAME,
        }))
        sys.exit(0)

    # --- Render cloud-init ---

    ci_dir = CLOUD_INIT_DIR / args.name
    ci_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(ci_dir, 0o755)  # traversable by libvirt-qemu
    allocated["cloud_init_dir"] = str(ci_dir)

    user_data_path = ci_dir / "user-data"
    ci_iso_path = ci_dir / "cidata.iso"

    if args.cloud_init_content:
        # Use pre-rendered cloud-init from caller
        with open(args.cloud_init_content, "r") as f:
            user_data = f.read()
    else:
        # Render via blockhost.cloud_init
        try:
            from blockhost.cloud_init import render_cloud_init

            blockchain = web3_config.get("blockchain", {})
            signing = web3_config.get("signing_page", {})
            auth = web3_config.get("auth", {})

            # Derive signing host from allocated IP
            signing_host = f"{ip}:{signing.get('port', 8080)}"

            variables = {
                "VM_NAME": args.name,
                "VM_IP": ip,
                "VM_IPV6": ipv6,
                "SIGNING_HOST": signing_host,
                "USERNAME": USERNAME,
                "NFT_TOKEN_ID": str(nft_token_id),
                "CHAIN_ID": str(blockchain.get("chain_id", "")),
                "NFT_CONTRACT": blockchain.get("nft_contract", ""),
                "RPC_URL": blockchain.get("rpc_url", ""),
                "OTP_LENGTH": str(auth.get("otp_length", 6)),
                "OTP_TTL": str(auth.get("otp_ttl_seconds", 300)),
                "SECRET_KEY": args.public_secret or "",
                "SSH_KEYS": "",
            }

            user_data = render_cloud_init("nft-auth.yaml", variables)
        except Exception as e:
            fail(f"Failed to render cloud-init: {e}", allocated)

    # Write user-data file
    user_data_path.write_text(user_data)

    # Generate cloud-init ISO via cloud-localds
    try:
        subprocess.run(
            ["cloud-localds", str(ci_iso_path), str(user_data_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        fail(f"cloud-localds failed: {e.stderr.strip()}", allocated)
    except FileNotFoundError:
        fail("cloud-localds not found (install cloud-image-utils)", allocated)

    os.chmod(ci_iso_path, 0o644)
    err("Cloud-init ISO created.")

    # --- Create disk overlay ---

    try:
        cmd = [
            "qemu-img", "create",
            "-f", "qcow2",
            "-b", str(TEMPLATE_IMAGE),
            "-F", "qcow2",
            str(disk_path),
            f"{args.disk}G",
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        fail(f"qemu-img create failed: {e.stderr.strip()}", allocated)

    os.chmod(disk_path, 0o644)
    allocated["disk_path"] = str(disk_path)
    err(f"Disk overlay created: {disk_path}")

    # --- Generate and write domain XML ---

    xml_dir = Path("/var/lib/blockhost/vms")
    xml_path = xml_dir / f"{args.name}.xml"

    domain_xml = generate_domain_xml(
        args.name, args.cpu, args.memory, str(disk_path),
        str(ci_iso_path), bridge_name,
    )

    xml_path.write_text(domain_xml)

    # --- Define + start domain via root agent ---

    try:
        from blockhost.root_agent import call, RootAgentError

        result = call("virsh-define", xml_path=str(xml_path))
        if not result.get("ok"):
            fail(f"virsh-define failed: {result.get('error')}", allocated)
        allocated["domain_defined"] = True
        err("Domain defined.")

        result = call("virsh-start", domain=args.name)
        if not result.get("ok"):
            fail(f"virsh-start failed: {result.get('error')}", allocated)
        err("Domain started.")
    except Exception as e:
        fail(f"Root agent error: {e}", allocated)

    # Clean up the XML file — libvirt has its own copy now
    xml_path.unlink(missing_ok=True)

    # --- Add IPv6 route if allocated ---

    if ipv6:
        try:
            from blockhost.root_agent import call
            call("ip6-route-add", address=f"{ipv6}/128", dev=bridge_name)
            err(f"IPv6 route added: {ipv6}/128 via {bridge_name}")
        except Exception as e:
            # Non-fatal — VM works without IPv6 route
            err(f"WARNING: Failed to add IPv6 route: {e}")

    # --- Register in database ---

    try:
        vm_record = db.register_vm(
            name=args.name,
            vmid=args.name,  # libvirt uses domain name as ID
            ip=ip,
            ipv6=ipv6,
            owner=args.owner_wallet,
            expiry_days=args.expiry_days,
            wallet_address=args.owner_wallet,
        )
        err("VM registered in database.")
    except Exception as e:
        fail(f"Database registration failed: {e}", allocated)

    # --- Output ---

    print(json.dumps({
        "status": "ok",
        "vm_name": args.name,
        "ip": ip,
        "ipv6": ipv6,
        "vmid": args.name,
        "nft_token_id": nft_token_id,
        "username": USERNAME,
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
