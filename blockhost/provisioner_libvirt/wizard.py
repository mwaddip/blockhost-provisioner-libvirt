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
    """
    # TODO: Implement storage pool creation
    # 1. Check if pool already exists (virsh pool-info)
    # 2. If not: define pool XML, build, start, autostart
    # 3. Verify pool is active
    #
    # virsh pool-define-as blockhost dir --target /var/lib/blockhost/vms
    # virsh pool-build blockhost
    # virsh pool-start blockhost
    # virsh pool-autostart blockhost

    return (False, "not yet implemented")


def finalize_network(config: dict) -> tuple[bool, Optional[str]]:
    """Create or verify the network configuration.

    Depending on network_mode:
    - "bridge": Verify the Linux bridge exists
    - "nat": Create a libvirt NAT network
    """
    # TODO: Implement network configuration
    # Bridge mode: verify bridge interface exists (ip link show <bridge>)
    # NAT mode: define libvirt network XML, start, autostart

    return (False, "not yet implemented")


def finalize_template(config: dict) -> tuple[bool, Optional[str]]:
    """Build the VM template image.

    Runs blockhost-build-template which downloads a cloud image
    and customizes it with libguestfs.
    """
    # TODO: Implement template build
    # subprocess.run(['blockhost-build-template'], check=True)

    return (False, "not yet implemented")


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
