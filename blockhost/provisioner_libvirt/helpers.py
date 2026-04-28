"""
Shared helpers for libvirt provisioner CLI scripts.

Read-only utilities the blockhost user can call directly (without going
through the root agent). Mutating operations belong in root-agent-actions/virsh.py.
"""

import subprocess


def get_vm_tap_interface(domain):
    """Discover the tap device for a domain's bridge interface.

    Parses ``virsh domiflist <domain>`` and returns the interface name
    (e.g. 'vnet0') of the first row whose connection type is 'bridge',
    or None if the domain has no bridge interface or virsh fails.
    """
    try:
        result = subprocess.run(
            ["virsh", "domiflist", domain],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    # Output format: header + separator + rows. Skip the first two lines.
    for line in result.stdout.strip().splitlines()[2:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "bridge":
            return parts[0]
    return None
