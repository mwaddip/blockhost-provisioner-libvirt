"""
libvirt/KVM wizard plugin for BlockHost installer.

Provides:
- Flask Blueprint with /wizard/libvirt route
- Finalization steps: storage, network, template
- Summary data for the summary page
"""

import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from flask import Blueprint, redirect, render_template, request, session, url_for

blueprint = Blueprint(
    "provisioner_libvirt",
    __name__,
    template_folder="templates",
)


# --- Wizard Route ---


@blueprint.route("/wizard/libvirt", methods=["GET", "POST"])
def wizard_libvirt():
    """libvirt configuration step."""
    detected = _detect_libvirt_resources()

    if request.method == "POST":
        # Query actual DHCP range from the default network if libvirtd is running
        dhcp = detected.get("default_network_dhcp", {})
        ip_network = dhcp.get("network", "192.168.122.0/24")
        ip_start = dhcp.get("start", "192.168.122.2")
        ip_end = dhcp.get("end", "192.168.122.254")
        gateway = dhcp.get("gateway", "192.168.122.1")

        session["libvirt"] = {
            "storage_pool": request.form.get("storage_pool", "blockhost"),
            "storage_path": request.form.get("storage_path", "/var/lib/blockhost/vms"),
            "wan_interface": request.form.get("wan_interface", ""),
            "ip_network": ip_network,
            "ip_start": ip_start,
            "ip_end": ip_end,
            "gateway": gateway,
            "gc_grace_days": int(request.form.get("gc_grace_days", 7)),
        }
        return redirect(url_for("wizard_ipv6"))

    return render_template("provisioner_libvirt/libvirt.html", detected=detected)


# --- Summary ---


def get_summary_data(session_data: dict) -> dict:
    """Return provisioner-specific summary data."""
    libvirt = session_data.get("libvirt", {})
    return {
        "storage_pool": libvirt.get("storage_pool"),
        "storage_path": libvirt.get("storage_path"),
        "wan_interface": libvirt.get("wan_interface"),
        "gc_grace_days": libvirt.get("gc_grace_days", 7),
    }


def get_summary_template() -> str:
    """Return the template name for the provisioner summary section."""
    return "provisioner_libvirt/summary_section.html"


# --- Finalization Steps ---


def get_finalization_steps() -> list[tuple]:
    """Return provisioner finalization steps.

    Each tuple: (step_id, display_name, callable)
    The callable signature: func(config: dict) -> tuple[bool, Optional[str]]
    """
    return [
        ("storage", "Configuring storage pool", finalize_storage),
        ("network", "Configuring network", finalize_network),
        ("template", "Building VM template", finalize_template),
    ]


# --- Finalization Functions ---


def finalize_storage(config: dict) -> tuple[bool, Optional[str]]:
    """Create or verify the libvirt storage pool.

    Creates a directory-based storage pool at the configured path.
    Idempotent: if the pool already exists and is active, succeeds immediately.
    """
    provisioner = config.get("provisioner", {})
    pool_name = provisioner.get("storage_pool", "blockhost")
    pool_path = provisioner.get("storage_path", "/var/lib/blockhost/vms")

    try:
        # Check if pool already exists
        result = subprocess.run(
            ["virsh", "pool-info", pool_name],
            capture_output=True, text=True, timeout=10,
        )
        pool_exists = result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return (False, f"Cannot query libvirt pools: {e}")

    if not pool_exists:
        # Create directory
        os.makedirs(pool_path, mode=0o750, exist_ok=True)

        # Define the pool
        result = subprocess.run(
            ["virsh", "pool-define-as", pool_name, "dir", "--target", pool_path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return (False, f"pool-define-as failed: {result.stderr.strip()}")

        # Build the pool (creates the directory structure)
        result = subprocess.run(
            ["virsh", "pool-build", pool_name],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return (False, f"pool-build failed: {result.stderr.strip()}")

    # Ensure pool is started
    result = subprocess.run(
        ["virsh", "pool-info", pool_name],
        capture_output=True, text=True, timeout=10,
    )
    if "inactive" in result.stdout.lower() or "State:" not in result.stdout:
        subprocess.run(
            ["virsh", "pool-start", pool_name],
            capture_output=True, text=True, timeout=10,
        )

    # Ensure pool autostarts
    subprocess.run(
        ["virsh", "pool-autostart", pool_name],
        capture_output=True, text=True, timeout=10,
    )

    # Verify pool is active
    result = subprocess.run(
        ["virsh", "pool-info", pool_name],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0 or "running" not in result.stdout.lower():
        return (False, f"Storage pool '{pool_name}' is not active after setup")

    return (True, None)


def finalize_network(config: dict) -> tuple[bool, Optional[str]]:
    """Discover Linux bridge and disable the default NAT network.

    The main repo creates a Linux bridge (br0) during first-boot and stores
    the name in /run/blockhost/bridge. VMs attach directly to this bridge.
    The libvirt default NAT network is disabled to avoid virbr0 subnet collisions.
    """
    bridge_name = _discover_bridge()
    if not bridge_name:
        return (False, "No Linux bridge found. "
                "Expected /run/blockhost/bridge or a bridge with a global IPv4.")

    # Verify bridge has an IP address
    try:
        result = subprocess.run(
            ["ip", "-4", "addr", "show", "dev", bridge_name],
            capture_output=True, text=True, timeout=5,
        )
        if "inet " not in result.stdout:
            return (False, f"Bridge '{bridge_name}' has no IPv4 address")
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return (False, f"Cannot check bridge '{bridge_name}': {e}")

    # Disable default NAT network to avoid virbr0 subnet collisions
    subprocess.run(
        ["virsh", "net-destroy", "default"],
        capture_output=True, timeout=10,
    )
    subprocess.run(
        ["virsh", "net-autostart", "default", "--disable"],
        capture_output=True, timeout=10,
    )

    # Store bridge name in config for later use
    provisioner = config.get("provisioner", {})
    provisioner["bridge"] = bridge_name
    config["provisioner"] = provisioner

    return (True, None)


def finalize_template(config: dict) -> tuple[bool, Optional[str]]:
    """Build the VM template image.

    Runs blockhost-build-template which downloads a cloud image
    and customizes it with libguestfs. This can take several minutes
    on first run (downloading ~700MB cloud image + customization).
    """
    try:
        result = subprocess.run(
            ["blockhost-build-template"],
            capture_output=True, text=True,
            timeout=1800,  # 30 min — image download + customize can be slow
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            return (False, f"Template build failed: {stderr[-500:] if len(stderr) > 500 else stderr}")
        return (True, None)
    except subprocess.TimeoutExpired:
        return (False, "Template build timed out (30 minutes)")
    except FileNotFoundError:
        return (False, "blockhost-build-template command not found")


# --- Helper Functions ---


def _discover_bridge() -> Optional[str]:
    """Find the Linux bridge to use for VM networking.

    1. Read /run/blockhost/bridge (written by first-boot)
    2. Fallback: scan /sys/class/net/*/bridge for any bridge with a global IPv4
    """
    # Canonical location written by first-boot
    bridge_file = Path("/run/blockhost/bridge")
    if bridge_file.exists():
        name = bridge_file.read_text().strip()
        if name:
            return name

    # Fallback: find any bridge with a global IPv4 address
    try:
        net_dir = Path("/sys/class/net")
        for iface in sorted(net_dir.iterdir()):
            if (iface / "bridge").is_dir():
                result = subprocess.run(
                    ["ip", "-4", "addr", "show", "dev", iface.name, "scope", "global"],
                    capture_output=True, text=True, timeout=5,
                )
                if "inet " in result.stdout:
                    return iface.name
    except Exception:
        pass

    return None


def _get_default_network_dhcp() -> dict:
    """Parse the default libvirt network XML for DHCP range and gateway.

    Returns dict with keys: network, start, end, gateway.
    Returns empty dict on failure.
    """
    try:
        result = subprocess.run(
            ["virsh", "net-dumpxml", "default"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return {}

        root = ET.fromstring(result.stdout)
        ip_elem = root.find(".//ip")
        if ip_elem is None:
            return {}

        address = ip_elem.get("address", "192.168.122.1")
        netmask = ip_elem.get("netmask", "255.255.255.0")

        # Convert netmask to CIDR prefix length
        import ipaddress
        network = ipaddress.IPv4Network(f"{address}/{netmask}", strict=False)

        dhcp_range = ip_elem.find("dhcp/range")
        if dhcp_range is not None:
            start = dhcp_range.get("start", "")
            end = dhcp_range.get("end", "")
        else:
            start = ""
            end = ""

        return {
            "network": str(network),
            "gateway": address,
            "start": start,
            "end": end,
        }
    except Exception:
        return {}


def _detect_libvirt_resources() -> dict:
    """Auto-detect libvirt configuration for form defaults."""
    detected = {
        "kvm_available": os.path.exists("/dev/kvm"),
        "libvirtd_running": False,
        "storage_pools": [],
        "wan_interfaces": [],
        "default_network_dhcp": {},
    }

    # Check libvirtd
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "libvirtd"],
            capture_output=True, text=True, timeout=5,
        )
        detected["libvirtd_running"] = result.stdout.strip() == "active"
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    # List existing storage pools
    try:
        result = subprocess.run(
            ["virsh", "pool-list", "--name"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            detected["storage_pools"] = [
                p.strip() for p in result.stdout.strip().split("\n") if p.strip()
            ]
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    # Detect WAN interface(s) — the one(s) with a default route
    try:
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                parts = line.split()
                try:
                    dev_idx = parts.index("dev")
                    detected["wan_interfaces"].append(parts[dev_idx + 1])
                except (ValueError, IndexError):
                    pass
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    # Detect default network DHCP range
    if detected["libvirtd_running"]:
        detected["default_network_dhcp"] = _get_default_network_dhcp()

    return detected
