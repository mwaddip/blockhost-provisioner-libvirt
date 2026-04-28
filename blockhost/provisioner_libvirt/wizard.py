"""
libvirt/KVM wizard plugin for BlockHost installer.

Provides:
- Flask Blueprint with /wizard/libvirt route
- Finalization steps: storage, network, db_config, template
- Summary data for the summary page
"""

import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import yaml
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
        # The default libvirt network's DHCP range is used as the BlockHost
        # IP pool — it's the only routable RFC1918 subnet on a fresh install.
        # finalize_network disables the libvirt default after we've harvested
        # the range here.
        dhcp = detected.get("default_network_dhcp", {})

        session["libvirt"] = {
            "storage_pool": request.form.get("storage_pool", "blockhost"),
            "storage_path": request.form.get("storage_path", "/var/lib/blockhost/vms"),
            "ip_network": dhcp.get("network", "192.168.122.0/24"),
            "ip_start": dhcp.get("start", "192.168.122.2"),
            "ip_end": dhcp.get("end", "192.168.122.254"),
            "gateway": dhcp.get("gateway", "192.168.122.1"),
            "gc_grace_days": int(request.form.get("gc_grace_days", 7)),
        }
        return redirect(url_for("wizard_connectivity"))

    return render_template("provisioner_libvirt/libvirt.html", detected=detected)


# --- Summary ---


def get_ui_params(session_data: dict) -> dict:
    """Return provisioner-specific UI parameters injected into all templates as prov_ui.

    libvirt has no web management UI, so return empty dict.
    All templates use | default() filters and will render with generic defaults.
    """
    return {}


def get_summary_data(session_data: dict) -> dict:
    """Return provisioner-specific summary data."""
    libvirt = session_data.get("libvirt", {})
    return {
        "storage_pool": libvirt.get("storage_pool"),
        "storage_path": libvirt.get("storage_path"),
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

    db_config runs after network so the discovered bridge is available.
    """
    return [
        ("storage", "Configuring storage pool", finalize_storage),
        ("network", "Configuring network", finalize_network),
        ("db_config", "Writing provisioner config", finalize_db_config),
        ("template", "Building VM template", finalize_template,
         "(this may take several minutes)"),
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

    # Disable default NAT network to avoid virbr0 subnet collisions.
    # Failure here previously went silent — virbr0 staying up is the bug
    # finalize_network exists to prevent. Treat already-inactive / not-found
    # as benign; everything else is an error.
    for cmd in (
        ["virsh", "net-destroy", "default"],
        ["virsh", "net-autostart", "default", "--disable"],
    ):
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            stderr_lower = (result.stderr or "").strip().lower()
            if "is not active" in stderr_lower or "not found" in stderr_lower:
                continue
            return (False, f"{' '.join(cmd)} failed: {result.stderr.strip()}")

    # Store bridge name in config for later use (finalize_db_config persists it)
    provisioner = config.get("provisioner", {})
    provisioner["bridge"] = bridge_name
    config["provisioner"] = provisioner

    return (True, None)


def finalize_db_config(config: dict) -> tuple[bool, Optional[str]]:
    """Write /etc/blockhost/db.yaml with the provisioner's runtime config.

    Mirror of the Proxmox provisioner's equivalent step. Without this, the
    bridge name and IP pool collected in the wizard never reach disk —
    vm-create then falls back to defaults that only work coincidentally.

    Reads from the in-memory config dict (populated by the POST handler
    and finalize_network). Writes to /etc/blockhost/db.yaml.
    """
    try:
        provisioner = config.get("provisioner", {})

        db_config = {
            "db_file": "/var/lib/blockhost/vm-db.json",
            "storage_pool": provisioner.get("storage_pool", "blockhost"),
            "storage_path": provisioner.get("storage_path", "/var/lib/blockhost/vms"),
            "bridge": provisioner.get("bridge", "br0"),
            "gc_grace_days": int(provisioner.get("gc_grace_days", 7)),
            "ip_pool": {
                "network": provisioner.get("ip_network", "192.168.122.0/24"),
                "start": provisioner.get("ip_start", "192.168.122.2"),
                "end": provisioner.get("ip_end", "192.168.122.254"),
                "gateway": provisioner.get("gateway", "192.168.122.1"),
            },
        }

        config_dir = Path("/etc/blockhost")
        config_dir.mkdir(parents=True, exist_ok=True)

        db_yaml_path = config_dir / "db.yaml"
        db_yaml_path.write_text(yaml.dump(db_config, default_flow_style=False))

        return (True, None)
    except Exception as e:
        return (False, f"Failed to write db.yaml: {e}")


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

    # Detect default network DHCP range — used as the BlockHost IP pool
    if detected["libvirtd_running"]:
        detected["default_network_dhcp"] = _get_default_network_dhcp()

    return detected
