"""
libvirt/KVM wizard plugin for BlockHost installer.

Provides:
- Flask Blueprint with /wizard/libvirt route
- Finalization steps: storage, network, template
- Summary data for the summary page
"""

import os
import subprocess
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
        session["libvirt"] = {
            "storage_pool": request.form.get("storage_pool", "blockhost"),
            "storage_path": request.form.get("storage_path", "/var/lib/blockhost/vms"),
            "network_mode": request.form.get("network_mode", "bridge"),
            "network_name": request.form.get("network_name", ""),
            "bridge_interface": request.form.get("bridge_interface", ""),
            "template_url": request.form.get("template_url", ""),
            "ip_network": request.form.get("ip_network"),
            "ip_start": request.form.get("ip_start"),
            "ip_end": request.form.get("ip_end"),
            "gateway": request.form.get("gateway"),
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
        "network_mode": libvirt.get("network_mode"),
        "network_name": libvirt.get("network_name"),
        "ip_start": libvirt.get("ip_start"),
        "ip_end": libvirt.get("ip_end"),
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
    libvirt = config.get("libvirt", {})
    pool_name = libvirt.get("storage_pool", "blockhost")
    pool_path = libvirt.get("storage_path", "/var/lib/blockhost/vms")

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
    """Create or verify the network configuration.

    Depending on network_mode:
    - "bridge": Verify the Linux bridge exists
    - "nat": Verify the libvirt default network is active
    """
    libvirt = config.get("libvirt", {})
    network_mode = libvirt.get("network_mode", "bridge")

    if network_mode == "bridge":
        bridge = libvirt.get("bridge_interface", "")
        if not bridge:
            return (False, "No bridge interface specified")

        # Verify bridge exists
        result = subprocess.run(
            ["ip", "link", "show", bridge],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return (False, f"Bridge interface '{bridge}' not found")

        return (True, None)

    # NAT mode: verify the libvirt network exists and is active
    net_name = libvirt.get("network_name", "default")

    result = subprocess.run(
        ["virsh", "net-info", net_name],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return (False, f"libvirt network '{net_name}' not found. Create it or switch to bridge mode.")

    # Ensure it's started
    if "inactive" in result.stdout.lower():
        subprocess.run(
            ["virsh", "net-start", net_name],
            capture_output=True, text=True, timeout=10,
        )

    # Ensure autostart
    subprocess.run(
        ["virsh", "net-autostart", net_name],
        capture_output=True, text=True, timeout=10,
    )

    # Verify active
    result = subprocess.run(
        ["virsh", "net-info", net_name],
        capture_output=True, text=True, timeout=10,
    )
    if "active" not in result.stdout.lower():
        return (False, f"libvirt network '{net_name}' could not be activated")

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


def _detect_libvirt_resources() -> dict:
    """Auto-detect libvirt configuration for form defaults."""
    detected = {
        "kvm_available": os.path.exists("/dev/kvm"),
        "libvirtd_running": False,
        "storage_pools": [],
        "networks": [],
        "bridges": [],
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

    # List existing networks
    try:
        result = subprocess.run(
            ["virsh", "net-list", "--name"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            detected["networks"] = [
                n.strip() for n in result.stdout.strip().split("\n") if n.strip()
            ]
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    # List Linux bridges
    try:
        result = subprocess.run(
            ["ip", "-o", "link", "show", "type", "bridge"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    parts = line.split(":")
                    if len(parts) >= 2:
                        detected["bridges"].append(parts[1].strip())
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    return detected
