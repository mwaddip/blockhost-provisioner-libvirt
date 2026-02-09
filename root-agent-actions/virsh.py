"""
libvirt/virsh actions for the BlockHost root agent.

Shipped by blockhost-provisioner-libvirt, loaded by the root agent daemon from
/usr/share/blockhost/root-agent-actions/.

Equivalent to qm.py in the Proxmox provisioner, but uses virsh instead of qm.
"""

import os
import re

from _common import (
    log,
    run,
)

# Domain name validation: alphanumeric, hyphens, underscores, dots
DOMAIN_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$')


def validate_domain(params):
    """Extract and validate domain name from params."""
    domain = params.get('domain', '')
    if not isinstance(domain, str) or not DOMAIN_RE.match(domain):
        raise ValueError(f'Invalid domain name: {domain}')
    return domain


def _handle_virsh_simple(params, subcommand, extra_args=(), timeout=120):
    """Run a simple virsh subcommand that only takes a domain name."""
    domain = validate_domain(params)
    rc, out, err = run(
        ['virsh', subcommand, domain] + list(extra_args),
        timeout=timeout,
    )
    if rc != 0:
        return {'ok': False, 'error': err or out}
    return {'ok': True, 'output': out}


def handle_virsh_define(params):
    """Define a domain from an XML file.

    params:
        xml_path (str): Path to domain XML (must be under /var/lib/blockhost/)
    """
    xml_path = params.get('xml_path', '')
    if not isinstance(xml_path, str) or not xml_path:
        return {'ok': False, 'error': 'xml_path is required'}
    if not xml_path.startswith('/var/lib/blockhost/'):
        return {'ok': False, 'error': 'xml_path must be under /var/lib/blockhost/'}
    if not os.path.isfile(xml_path):
        return {'ok': False, 'error': f'XML file not found: {xml_path}'}

    rc, out, err = run(['virsh', 'define', xml_path], timeout=30)
    if rc != 0:
        return {'ok': False, 'error': err or out}
    return {'ok': True, 'output': out}


def handle_virsh_undefine(params):
    """Undefine a domain and optionally remove storage.

    params:
        domain (str): Domain name
        remove_storage (bool): Also remove associated storage volumes
    """
    domain = validate_domain(params)
    cmd = ['virsh', 'undefine', domain]
    if params.get('remove_storage', False):
        cmd.append('--remove-all-storage')

    rc, out, err = run(cmd, timeout=60)
    if rc != 0:
        return {'ok': False, 'error': err or out}
    return {'ok': True, 'output': out}


ACTIONS = {
    'virsh-start':    lambda p: _handle_virsh_simple(p, 'start'),
    'virsh-destroy':  lambda p: _handle_virsh_simple(p, 'destroy'),        # force stop (confusing, blame libvirt)
    'virsh-shutdown': lambda p: _handle_virsh_simple(p, 'shutdown', timeout=300),  # graceful ACPI
    'virsh-reboot':   lambda p: _handle_virsh_simple(p, 'reboot'),
    'virsh-define':   handle_virsh_define,
    'virsh-undefine': handle_virsh_undefine,
}
